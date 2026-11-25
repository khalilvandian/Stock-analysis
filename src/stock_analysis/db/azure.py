"""Keep the Azure PostgreSQL firewall open to this computer's current public IP.

Home connections get a new public IP now and then; the server's firewall only lets listed
addresses in. `python -m stock_analysis.db allow-my-ip` looks up the current IP and creates or
updates one firewall rule (default name `home`) on the server named in config/database.toml
(`azure_server`, `azure_resource_group` under the target). It uses the Azure CLI, signed in
once with `az login`. No secrets are involved.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

from . import target_settings

IP_SERVICE = "https://api.ipify.org"
DEFAULT_AZ = Path(r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")


def az_command() -> str:
    found = shutil.which("az") or (str(DEFAULT_AZ) if DEFAULT_AZ.exists() else None)
    if not found:
        raise RuntimeError("Azure CLI not found: winget install Microsoft.AzureCLI, then az login")
    return found


def public_ip() -> str:
    with urllib.request.urlopen(IP_SERVICE, timeout=10) as response:
        return response.read().decode().strip()


def allow_my_ip(target: str = "server", rule: str = "home", ip: str | None = None) -> str:
    """Create or update a firewall rule for this computer's public IP, or for `ip` (e.g. the
    exit address of Claude's cloud proxy, rule `claude-cloud`)."""
    settings = target_settings(target)
    server, group = settings.get("azure_server"), settings.get("azure_resource_group")
    if not server or not group:
        raise ValueError(f"Target {target!r} needs azure_server and azure_resource_group")
    if ip:  # one address, or a range such as 160.79.104.0/21
        network = ipaddress.ip_network(ip, strict=False)
        ip, last = str(network[0]), str(network[-1])
    else:
        ip = last = public_ip()
    result = subprocess.run(
        [
            az_command(),
            "postgres",
            "flexible-server",
            "firewall-rule",
            "create",
            "--resource-group",
            group,
            "--server-name",
            server,
            "--name",
            rule,
            "--start-ip-address",
            ip,
            "--end-ip-address",
            last,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        hint = " (run az login first)" if "az login" in result.stderr else ""
        raise RuntimeError(f"Azure CLI failed{hint}: {result.stderr.strip()[-500:]}")
    saved = json.loads(result.stdout or "{}")
    allowed = ip if ip == last else f"{ip} to {last}"
    return f"Firewall rule {saved.get('name', rule)!r} on {server} now allows {allowed}"


# ---------------------------------------------------------------- inside Azure (the ingest job)

ARM = "https://management.azure.com"
FIREWALL_API = "2022-12-01"


def _rule_url(subscription: str, group: str, server: str, rule: str) -> str:
    return (
        f"{ARM}/subscriptions/{subscription}/resourceGroups/{group}/providers/"
        f"Microsoft.DBforPostgreSQL/flexibleServers/{server}/firewallRules/{rule}"
        f"?api-version={FIREWALL_API}"
    )


def managed_identity_token(http, resource: str = ARM + "/") -> str | None:
    """A token for `resource` (Azure Resource Manager by default) from the managed identity of
    a Container App or Job (IDENTITY_ENDPOINT and IDENTITY_HEADER are set there); None elsewhere."""
    import os

    endpoint, header = os.environ.get("IDENTITY_ENDPOINT"), os.environ.get("IDENTITY_HEADER")
    if not endpoint or not header:
        return None
    r = http.get(
        endpoint,
        params={"resource": resource, "api-version": "2019-08-01"},
        headers={"X-IDENTITY-HEADER": header},
    )
    r.raise_for_status()
    return r.json()["access_token"]


class JobFirewall:
    """Let this run of the ingest job through the database firewall: on entry, set the rule
    `rule` to this container's public IP (through Azure Resource Manager, as the job's managed
    identity, which needs rights on the server only); on exit, delete it. Outside Azure (no
    managed identity or no AZURE_SUBSCRIPTION_ID) it does nothing."""

    def __init__(self, target: str | None, rule: str = "ingest-job", http=None, sleep=None):
        import os
        import time

        import httpx

        self.settings = target_settings(target)
        self.subscription = os.environ.get("AZURE_SUBSCRIPTION_ID")
        self.rule, self.http = rule, http or httpx.Client(timeout=60)
        self.sleep = sleep or time.sleep
        self.url: str | None = None
        self.headers: dict = {}

    def _wait(self, r) -> None:
        """Azure applies a firewall change asynchronously: follow its operation to the end."""
        poll = r.headers.get("Azure-AsyncOperation")
        if not poll:
            return
        for _ in range(60):
            s = self.http.get(poll, headers=self.headers)
            status = s.json().get("status") if s.status_code == 200 else None
            if status == "Succeeded":
                return
            if status in ("Failed", "Canceled"):
                raise RuntimeError(f"Firewall change {status}: {s.text[:300]}")
            self.sleep(5)
        raise RuntimeError("Firewall change did not finish in 5 minutes")

    def __enter__(self) -> str | None:
        server = self.settings.get("azure_server")
        group = self.settings.get("azure_resource_group")
        token = managed_identity_token(self.http) if self.subscription else None
        if not (token and server and group):
            return None
        self.headers = {"Authorization": f"Bearer {token}"}
        ip = self.http.get(IP_SERVICE).text.strip()
        ipaddress.ip_address(ip)  # fails loudly on anything but an address
        self.url = _rule_url(self.subscription, group, server, self.rule)
        body = {"properties": {"startIpAddress": ip, "endIpAddress": ip}}
        r = self.http.put(self.url, json=body, headers=self.headers)
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"Firewall rule failed ({r.status_code}): {r.text[:300]}")
        self._wait(r)
        return ip

    def __exit__(self, *exc) -> None:
        if self.url:
            try:
                r = self.http.delete(self.url, headers=self.headers)
                if r.status_code in (200, 202):
                    self._wait(r)
            except Exception as e:  # a rule left behind is replaced by the next run
                print(f"Could not remove firewall rule {self.rule}: {e}")

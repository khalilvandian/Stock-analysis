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
    ip = str(ipaddress.ip_address(ip)) if ip else public_ip()
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
            ip,
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
    return f"Firewall rule {saved.get('name', rule)!r} on {server} now allows {ip}"

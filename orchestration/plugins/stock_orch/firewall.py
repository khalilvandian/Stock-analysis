"""Let this container through the database firewall (issue #30): the Airflow UI's Container
App has no fixed outbound address, so at each start it sets its own rule on stock-db-bk to
its current public IP, as the jobs do (stock_analysis.db.azure.JobFirewall), with its managed
identity (Contributor on the server only). The rule stays while the app sleeps; the next
start replaces it.

    python -m stock_orch.firewall airflow-ui && exec airflow api-server --apps core

Settings: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP (stock-rg), AZURE_DB_SERVER (stock-db-bk).
Outside Azure (no managed identity) it does nothing.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import time

import httpx

ARM = "https://management.azure.com"
IP_SERVICE = "https://api.ipify.org"


def token(http: httpx.Client) -> str | None:
    endpoint, header = os.environ.get("IDENTITY_ENDPOINT"), os.environ.get("IDENTITY_HEADER")
    if not endpoint or not header:
        return None
    r = http.get(
        endpoint,
        params={"resource": ARM + "/", "api-version": "2019-08-01"},
        headers={"X-IDENTITY-HEADER": header},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def open_rule(rule: str, http: httpx.Client, sleep=time.sleep) -> str | None:
    bearer = token(http)
    if not bearer:
        return None
    group = os.environ.get("AZURE_RESOURCE_GROUP", "stock-rg")
    server = os.environ.get("AZURE_DB_SERVER", "stock-db-bk")
    url = (
        f"{ARM}/subscriptions/{os.environ['AZURE_SUBSCRIPTION_ID']}/resourceGroups/{group}/"
        f"providers/Microsoft.DBforPostgreSQL/flexibleServers/{server}/firewallRules/{rule}"
        "?api-version=2022-12-01"
    )
    ip = http.get(IP_SERVICE).text.strip()
    ipaddress.ip_address(ip)
    headers = {"Authorization": f"Bearer {bearer}"}
    r = http.put(url, json={"properties": {"startIpAddress": ip, "endIpAddress": ip}},
                 headers=headers)  # fmt: skip
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"Firewall rule failed ({r.status_code}): {r.text[:300]}")
    poll = r.headers.get("Azure-AsyncOperation")
    for _ in range(60 if poll else 0):
        status = http.get(poll, headers=headers).json().get("status")
        if status == "Succeeded":
            break
        if status in ("Failed", "Canceled"):
            raise RuntimeError(f"Firewall change {status}")
        sleep(5)
    return ip


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "airflow-ui"
    with httpx.Client(timeout=60) as client:
        ip = open_rule(name, client)
    print(f"Firewall rule {name}: {ip}" if ip else "Not on Azure: no firewall rule")

"""Start the Airflow UI on Azure (issue #30): open this container's database firewall rule
(stock_orch.firewall), then become `airflow api-server --apps core`. The Container App runs
it as `python /opt/stock/orchestration/plugins/stock_orch/ui.py`: no argument starts with a
dash, which the Azure CLI would read as one of its own options."""

from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock_orch.firewall import open_rule  # noqa: E402

if __name__ == "__main__":
    with httpx.Client(timeout=60) as client:
        ip = open_rule("airflow-ui", client)
    print(f"Firewall rule airflow-ui: {ip}" if ip else "Not on Azure: no firewall rule", flush=True)
    port = os.environ.get("PORT", "8080")
    os.execvp(
        "airflow", ["airflow", "api-server", "--apps", "core", "--workers", "1", "--port", port]
    )

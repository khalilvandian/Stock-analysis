"""The proxy rules for database connections (no network)."""

from __future__ import annotations

import pytest

from stock_analysis.db import tunnel

CLAUDE_NO_PROXY = (
    "localhost,127.0.0.1,::1,127.0.0.0/8,169.254.0.0/16,api.anthropic.com,pypi.org,"
    "host.docker.internal,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc.cluster.local,"
    "*.svc.cluster.local"
)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("stock-db-bk.postgres.database.azure.com", False),
        ("172.213.20.101", False),
        ("127.0.0.1", True),
        ("localhost", True),
        ("10.1.2.3", True),
        ("db.svc.cluster.local", True),
        ("PyPI.org", True),
    ],
)
def test_no_proxy_rules(host: str, expected: bool) -> None:
    assert tunnel.bypassed(host, CLAUDE_NO_PROXY) is expected


def test_proxy_for_reads_the_environment(monkeypatch) -> None:
    for name in (*tunnel.PROXY_VARS, "NO_PROXY", "no_proxy", "STOCK_DB_PROXY"):
        monkeypatch.delenv(name, raising=False)
    assert tunnel.proxy_for("db.example.com") is None
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:3128")
    assert tunnel.proxy_for("db.example.com") == "http://127.0.0.1:3128"
    monkeypatch.setenv("no_proxy", "example.com")
    assert tunnel.proxy_for("db.example.com") is None
    monkeypatch.delenv("no_proxy")
    monkeypatch.setenv("STOCK_DB_PROXY", "off")
    assert tunnel.proxy_for("db.example.com") is None

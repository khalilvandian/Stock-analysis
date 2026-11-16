"""Diagnose a connection to a database target, step by step. Meant for a new place (a Claude
cloud session, another computer) to find out quickly why it can or can't reach the database.

    uv run python -m stock_analysis.db ping --target server-reader

Steps: this machine's public IP and proxy settings, DNS, a plain TCP connection to the port,
then a real login (TLS, user, password) showing the address the database sees. Each failure
says what usually causes it.
"""

from __future__ import annotations

import os
import re
import socket
import struct
import urllib.request
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import text

from . import ROOT, Database, hide_password, target_settings, tunnel


def line(status: str, step: str, detail: str = "") -> None:
    print(f"{status:4}  {step:<22} {detail}")


def ping(target: str | None = None) -> int:
    load_dotenv(ROOT / ".env")
    try:
        settings = target_settings(target)
    except ValueError as exc:
        line("FAIL", "target", str(exc))
        return 1
    url = settings["url"]
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or 5432
    line("INFO", "target", f"{settings['name']}: {hide_password(url)}")

    proxies = {k: v for k, v in os.environ.items() if k.lower() in ("https_proxy", "http_proxy",
               "all_proxy")}  # fmt: skip
    line("INFO", "proxy settings", ", ".join(f"{k} set" for k in proxies) or "none")
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            line("INFO", "public IP (HTTPS)", r.read().decode().strip())
    except Exception as exc:
        line("INFO", "public IP (HTTPS)", f"unknown ({type(exc).__name__})")

    try:
        addresses = sorted({a[4][0] for a in socket.getaddrinfo(host, port)})
        line("PASS", "DNS", f"{host} -> {', '.join(addresses)}")
    except OSError as exc:
        line("FAIL", "DNS", f"{host}: {exc} (no DNS: the network blocks lookups or the name)")
        return 1

    proxy = tunnel.proxy_for(host)
    how = "through the HTTP proxy (CONNECT tunnel)" if proxy else "direct"
    line("INFO", "route", how)
    try:
        sock = (
            tunnel.open_tunnel(proxy, host, port)
            if proxy
            else socket.create_connection((host, port), timeout=10)
        )
    except OSError as exc:
        line("FAIL", "TCP connect", f"port {port}, {how}: {exc}")
        print(
            "      A timeout or refusal here means the network between this machine and the\n"
            "      database blocks the connection: the database firewall (allowed IPs), or this\n"
            "      machine's network (e.g. a proxy that refuses the port)."
        )
        return 1
    # PostgreSQL's SSLRequest: a real server answers one byte, S or N.
    try:
        with sock:
            sock.settimeout(10)
            sock.sendall(struct.pack("!ii", 8, 80877103))
            answer = sock.recv(1)
    except OSError as exc:
        answer = f"{type(exc).__name__}".encode()
    if answer not in (b"S", b"N"):
        line("FAIL", "PostgreSQL answer", f"none ({answer.decode(errors='replace') or 'closed'})")
        print(
            "      The connection opened but no PostgreSQL server answered. Usually the database\n"
            "      firewall drops this machine's address (the public IP above): add it as a rule."
        )
        return 1
    line("PASS", "TCP connect", f"port {port}, {how}; PostgreSQL answered")

    env = settings.get("password_env")
    if env and not os.environ.get(env):
        line("FAIL", "password", f"{env} is not set in this environment")
        return 1
    db = Database(url, os.environ.get(env) if env else None, read_only=True)
    try:
        with db.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT current_user, inet_client_addr(), version(), "
                    "(SELECT MAX(version) FROM schema_version)"
                )
            ).one()
        line("PASS", "login", f"as {row[0]}, the database sees this machine as {row[1]}")
        line("PASS", "server", f"{row[2].split(',')[0]}, schema version {row[3]}")
        return 0
    except Exception as exc:
        message = str(getattr(exc, "orig", exc)).strip().split("\n")[0]
        seen = re.search(r'host "([^"]+)"', message)
        line("FAIL", "login", message[:200])
        if seen:
            print(
                f"      The database firewall doesn't allow {seen.group(1)}. Add it as a rule\n"
                "      (Azure portal: server > Networking, or az postgres flexible-server\n"
                "      firewall-rule create), then run ping again."
            )
        elif "password" in message.lower():
            print(f"      Wrong password: check {env}.")
        return 1
    finally:
        db.close()

"""Send PostgreSQL connections through an HTTP proxy, for networks that only allow the proxy.

Claude's cloud sessions reach the internet only through an HTTP proxy (`HTTPS_PROXY`); a direct
connection to the database's port is refused. The proxy does tunnel any port with HTTP CONNECT,
but PostgreSQL drivers don't use proxies. So when `HTTPS_PROXY` is set (and `NO_PROXY` doesn't
exclude the host), `Database` starts a small forwarder on 127.0.0.1: every connection to it gets
its own CONNECT tunnel to the database. TLS still runs end to end between psycopg and the server;
the forwarder and the proxy only see encrypted bytes.

`STOCK_DB_PROXY=off` disables it. On a normal PC no proxy is set and nothing changes.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import socket
import threading
from urllib.parse import unquote, urlparse

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")


def bypassed(host: str, no_proxy: str) -> bool:
    """Whether NO_PROXY (names, .suffixes, *, IPs, CIDR ranges) excludes this host."""
    host = host.lower()
    for entry in (e.strip().lower() for e in no_proxy.split(",")):
        if not entry:
            continue
        if entry == "*":
            return True
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            name = entry.lstrip("*").lstrip(".")
            if host == name or host.endswith("." + name):
                return True
            continue
        try:
            if ipaddress.ip_address(host) in network:
                return True
        except ValueError:
            pass
    return False


def proxy_for(host: str) -> str | None:
    """The proxy to use for this host, or None for a direct connection."""
    if os.environ.get("STOCK_DB_PROXY", "").lower() in ("off", "0", "no", "false"):
        return None
    proxy = next((os.environ[k] for k in PROXY_VARS if os.environ.get(k)), None)
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if not proxy or bypassed(host, no_proxy):
        return None
    return proxy


def open_tunnel(proxy: str, host: str, port: int, timeout: float = 10) -> socket.socket:
    """A socket connected to host:port through the proxy's CONNECT method."""
    p = urlparse(proxy if "://" in proxy else "http://" + proxy)
    if p.scheme != "http":
        raise OSError(f"proxy scheme {p.scheme!r} is not supported (only http://)")
    sock = socket.create_connection((p.hostname, p.port or 80), timeout=timeout)
    try:
        request = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        if p.username:
            user = f"{unquote(p.username)}:{unquote(p.password or '')}"
            request += f"Proxy-Authorization: Basic {base64.b64encode(user.encode()).decode()}\r\n"
        sock.sendall((request + "\r\n").encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("the proxy closed the connection during CONNECT")
            reply += chunk
            if len(reply) > 65536:
                raise OSError("the proxy's CONNECT reply is too long")
        status = reply.split(b"\r\n", 1)[0].decode(errors="replace")
        if status.split(" ")[1:2] != ["200"]:
            raise OSError(f"the proxy refused the tunnel: {status}")
        if reply.split(b"\r\n\r\n", 1)[1]:
            raise OSError("the proxy sent data before the database did")
        sock.settimeout(None)
        return sock
    except BaseException:
        sock.close()
        raise


def pipe(source: socket.socket, target: socket.socket) -> None:
    try:
        while data := source.recv(65536):
            target.sendall(data)
    except OSError:
        pass
    finally:
        for s in (source, target):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class Forwarder:
    """Listens on 127.0.0.1 and tunnels each connection to host:port through the proxy."""

    def __init__(self, proxy: str, host: str, port: int):
        self.proxy, self.host, self.port = proxy, host, port
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.local_port = self.listener.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True, name="db-tunnel").start()

    def serve(self) -> None:
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(client,), daemon=True).start()

    def handle(self, client: socket.socket) -> None:
        try:
            upstream = open_tunnel(self.proxy, self.host, self.port)
        except OSError:
            client.close()
            return
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        pipe(upstream, client)
        client.close()
        upstream.close()


_forwarders: dict[tuple[str, str, int], Forwarder] = {}
_lock = threading.Lock()


def route(host: str, port: int) -> int | None:
    """The local port to connect to instead of host:port, or None to connect directly."""
    proxy = proxy_for(host)
    if not proxy:
        return None
    with _lock:
        key = (proxy, host, port)
        if key not in _forwarders:
            _forwarders[key] = Forwarder(proxy, host, port)
        return _forwarders[key].local_port

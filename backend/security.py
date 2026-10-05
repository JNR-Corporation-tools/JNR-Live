from __future__ import annotations

import ipaddress
import secrets
import socket
from urllib.parse import urlsplit


ALLOWED_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def new_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def constant_time_equal(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return secrets.compare_digest(left, right)


def validate_loopback_target(host: str) -> None:
    normalized = host.strip().lower().rstrip(".")
    if normalized == "localhost":
        return
    try:
        ip = ipaddress.ip_address(normalized)
        if ip.is_loopback:
            return
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve upstream host: {host}") from exc
    if not infos or any(not ipaddress.ip_address(info[4][0]).is_loopback for info in infos):
        raise ValueError("Upstream host must resolve only to loopback addresses")


def validate_upstream_url(url: str) -> tuple[str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Upstream URL must include http:// or https:// and a host")
    validate_loopback_target(parsed.hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def safe_target_url(base: str, path: str, query: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}" + (f"?{query}" if query else "")

from __future__ import annotations

import ipaddress
import socket
from dataclasses import asdict

import psutil


def is_private_lan_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        return ip.version == 4 and not ip.is_loopback and not ip.is_link_local
    except ValueError:
        return False


def detect_ipv4_interfaces() -> list[dict]:
    results: list[dict] = []
    for name, addresses in psutil.net_if_addrs().items():
        for addr in addresses:
            if addr.family != socket.AF_INET:
                continue
            ip = addr.address
            results.append(
                {
                    "name": name,
                    "ip": ip,
                    "netmask": addr.netmask,
                    "is_loopback": ip == "127.0.0.1",
                    "is_lan": is_private_lan_ipv4(ip),
                    "label": f"{name} — {ip}",
                }
            )
    return sorted(results, key=lambda item: (not item["is_lan"], item["name"], item["ip"]))


def choose_default_interface() -> str:
    for item in detect_ipv4_interfaces():
        if item["is_lan"]:
            return item["ip"]
    return "127.0.0.1"


def local_hostname() -> str:
    return socket.gethostname()

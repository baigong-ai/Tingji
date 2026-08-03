"""Optional DNS hosts file workaround.

Reads `dns_hosts.txt` (if present in project root) and monkey-patches
`socket.getaddrinfo` to return the listed IPs without hitting the system
resolver. Useful on machines where mDNSResponder fails to resolve
certain domains (e.g. modelscope.cn) but direct IP access works.

File format (same as /etc/hosts):
    47.92.141.220 www.modelscope.cn
    39.99.133.195 modelscope.cn

Usage in app.main:
    from app.dns_hosts import install_if_present
    install_if_present()
"""
import socket
from pathlib import Path
from typing import Callable

_ORIG_GETADDRINFO: Callable = socket.getaddrinfo
_ORIG_GETHOSTBYNAME: Callable = socket.gethostbyname
_MAPPING: dict[str, str] = {}
_INSTALLED = False


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host and host in _MAPPING:
        ip = _MAPPING[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port if port else 0))]
    return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)


def _patched_gethostbyname(host):
    if host and host in _MAPPING:
        return _MAPPING[host]
    return _ORIG_GETHOSTBYNAME(host)


def install_if_present(path: str = "dns_hosts.txt") -> bool:
    """Install the hosts override if the file exists. Returns True if installed."""
    global _INSTALLED, _MAPPING
    if _INSTALLED:
        return True
    p = Path(path)
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        ip, host = parts
        _MAPPING[host] = ip
    if not _MAPPING:
        return False
    socket.getaddrinfo = _patched_getaddrinfo
    socket.gethostbyname = _patched_gethostbyname
    _INSTALLED = True
    return True

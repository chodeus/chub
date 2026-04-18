"""
SSRF protection helpers for CHUB.

Blocks outbound HTTP probes to cloud-metadata endpoints and (optionally)
link-local / loopback ranges that a user-supplied instance URL could target.
Lives separately from path_safety because the blast radius is different:
this is about where *we* connect, not where we read on disk.
"""

import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse

# Cloud-metadata / orchestrator endpoints that should never be reachable
# from a user-supplied instance URL.
_BLOCKED_HOSTS = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure IMDS
        "metadata.google.internal",
        "metadata",
        "metadata.aws.internal",
    }
)


def _resolve_host(host: str) -> Optional[ipaddress._BaseAddress]:
    try:
        ip = ipaddress.ip_address(host)
        return ip
    except ValueError:
        pass
    try:
        info = socket.getaddrinfo(host, None)
        if info:
            return ipaddress.ip_address(info[0][4][0])
    except (socket.gaierror, ValueError, IndexError):
        return None
    return None


def is_safe_url(url: str, allow_private: bool = True) -> Tuple[bool, str]:
    """
    Return (ok, reason). `allow_private=True` permits RFC1918 / loopback ranges,
    since homelab ARR/Plex instances are typically on the local network.
    Cloud-metadata endpoints are always blocked.
    """
    if not url or not isinstance(url, str):
        return False, "empty URL"
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "malformed URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"disallowed scheme: {parsed.scheme!r}"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "missing host"
    if host in _BLOCKED_HOSTS:
        return False, f"blocked host: {host}"
    ip = _resolve_host(host)
    if ip is not None:
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, f"disallowed address class: {ip}"
        if ip.is_link_local:
            return False, f"link-local address: {ip}"
        if not allow_private and (ip.is_private or ip.is_loopback):
            return False, f"private/loopback address: {ip}"
        if str(ip) in _BLOCKED_HOSTS:
            return False, f"blocked host: {ip}"
    return True, "ok"

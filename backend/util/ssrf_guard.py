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
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests

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

    Note: this validates the hostname's resolved IP *once*; the subsequent
    requests.get re-resolves DNS, so a rebinding host could in theory pass the
    check and then connect elsewhere (TOCTOU). It is not pinned to the resolved
    IP. This is acceptable today because every caller's URL is either built from
    a hardcoded base (e.g. image.tmdb.org) or validated with allow_private=False
    and allow_redirects disabled, so there is no reachable rebinding sink. If a
    future caller fetches a fully attacker-controlled host, pin the connection
    to the validated IP instead of re-resolving.
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
    # Fail closed: an unresolvable host must not pass (skipping the checks below
    # would let a rebinding/DNS-blip host through).
    if ip is None:
        return False, f"could not resolve host: {host}"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False, f"disallowed address class: {ip}"
    if ip.is_link_local:
        return False, f"link-local address: {ip}"
    if not allow_private and (ip.is_private or ip.is_loopback):
        return False, f"private/loopback address: {ip}"
    if str(ip) in _BLOCKED_HOSTS:
        return False, f"blocked host: {ip}"
    return True, "ok"


def safe_external_get(
    url: str, *, timeout: float = 10, headers: Optional[dict] = None
) -> "requests.Response":
    """GET an untrusted external URL with SSRF protection. Validates the host
    (private/loopback/metadata blocked), disables redirects, and pins http to the
    validated IP so DNS can't rebind between the check and the connect. https is
    left on its hostname — TLS cert verification (on by default) rejects a rebind
    to a mismatched internal certificate. Raises ValueError when the URL is unsafe.
    """
    ok, reason = is_safe_url(url, allow_private=False)
    if not ok:
        raise ValueError(reason)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    ip = _resolve_host(host)
    if ip is None:
        raise ValueError(f"could not resolve host: {host}")

    target = url
    req_headers = dict(headers or {})
    if parsed.scheme == "http":
        host_lit = f"[{ip}]" if ":" in str(ip) else str(ip)
        netloc = host_lit if parsed.port is None else f"{host_lit}:{parsed.port}"
        target = urlunsplit(urlsplit(url)._replace(netloc=netloc))
        req_headers["Host"] = host if parsed.port is None else f"{host}:{parsed.port}"
    return requests.get(
        target, headers=req_headers, timeout=timeout, allow_redirects=False
    )

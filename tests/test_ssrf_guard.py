"""Tests for backend/util/ssrf_guard.py — outbound URL safety check."""

import socket
from unittest.mock import patch

import pytest

from backend.util.ssrf_guard import is_safe_url


# --- Basic structural rejects ---


@pytest.mark.parametrize("bad", ["", None, 123])
def test_empty_or_non_string_rejected(bad):
    ok, _ = is_safe_url(bad)  # type: ignore[arg-type]
    assert ok is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/foo",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "gopher://localhost",
    ],
)
def test_disallowed_schemes(url):
    ok, reason = is_safe_url(url)
    assert ok is False
    assert "scheme" in reason


def test_missing_host():
    ok, reason = is_safe_url("http://")
    assert ok is False
    assert "host" in reason


# --- Blocked hosts (cloud metadata) ---


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
        "metadata.aws.internal",
    ],
)
def test_metadata_endpoints_blocked(host):
    ok, reason = is_safe_url(f"http://{host}/latest/meta-data")
    assert ok is False
    assert "blocked" in reason or "link-local" in reason


def test_metadata_endpoint_blocked_https():
    ok, _ = is_safe_url("https://169.254.169.254/")
    assert ok is False


# --- Private/loopback handling (default allow_private=True) ---


def test_loopback_allowed_by_default():
    ok, reason = is_safe_url("http://127.0.0.1:8989/api")
    assert ok is True, reason


def test_private_rfc1918_allowed_by_default():
    ok, reason = is_safe_url("http://192.168.1.100:7878/")
    assert ok is True, reason


def test_loopback_blocked_when_disallowed():
    ok, reason = is_safe_url("http://127.0.0.1/", allow_private=False)
    assert ok is False
    assert "private" in reason or "loopback" in reason


def test_private_blocked_when_disallowed():
    ok, _ = is_safe_url("http://10.0.0.1/", allow_private=False)
    assert ok is False


# --- DNS-based handling ---


def test_public_hostname_resolved_to_safe_ip():
    """A hostname that resolves to a public address should pass."""
    fake_info = [(socket.AF_INET, None, None, "", ("8.8.8.8", 0))]
    with patch("backend.util.ssrf_guard.socket.getaddrinfo", return_value=fake_info):
        ok, reason = is_safe_url("http://example.com/")
        assert ok is True, reason


def test_hostname_resolving_to_metadata_ip_blocked():
    fake_info = [(socket.AF_INET, None, None, "", ("169.254.169.254", 0))]
    with patch("backend.util.ssrf_guard.socket.getaddrinfo", return_value=fake_info):
        ok, reason = is_safe_url("http://evil.example/")
        assert ok is False
        # Could be flagged as link-local or blocked host depending on order
        assert "169.254" in reason or "blocked" in reason or "link-local" in reason


def test_unresolvable_hostname_fails_closed():
    """An unresolvable host must fail closed — otherwise a rebinding/blip host
    skips the IP checks and slips through."""
    with patch(
        "backend.util.ssrf_guard.socket.getaddrinfo", side_effect=socket.gaierror()
    ):
        ok, _ = is_safe_url("http://unresolvable-host.invalid/")
        assert ok is False

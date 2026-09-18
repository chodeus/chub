"""Tests for backend/util/rate_limiter.py — token bucket limiter."""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.util.rate_limiter import RateLimiter


def make_request(path="/login", ip="1.2.3.4", headers=None):
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host=ip),
        headers=dict(headers or {}),
    )


def test_invalid_init_raises():
    with pytest.raises(ValueError):
        RateLimiter(rate=0, burst=5)
    with pytest.raises(ValueError):
        RateLimiter(rate=1, burst=0)
    with pytest.raises(ValueError):
        RateLimiter(rate=-1, burst=5)


def test_first_request_passes():
    limiter = RateLimiter(rate=1, burst=3)
    limiter(make_request())  # should not raise


def test_burst_capacity_then_throttle():
    """Should allow `burst` requests, then 429."""
    limiter = RateLimiter(rate=0.001, burst=3)  # near-zero refill
    req = make_request()
    # First three pass
    limiter(req)
    limiter(req)
    limiter(req)
    with pytest.raises(HTTPException) as excinfo:
        limiter(req)
    assert excinfo.value.status_code == 429
    assert "Retry-After" in excinfo.value.headers


def test_refill_over_time():
    limiter = RateLimiter(rate=10, burst=2)
    req = make_request()
    limiter(req)
    limiter(req)

    base = time.monotonic()
    # Advance monotonic time by 1s -> bucket refills by 10 tokens, capped at 2
    with patch("backend.util.rate_limiter.time.monotonic", return_value=base + 1.0):
        limiter(req)  # should pass


def test_per_ip_separation():
    limiter = RateLimiter(rate=0.001, burst=1)
    limiter(make_request(ip="1.1.1.1"))
    # different IP keeps its own bucket
    limiter(make_request(ip="2.2.2.2"))
    # same IP again -> blocked
    with pytest.raises(HTTPException):
        limiter(make_request(ip="1.1.1.1"))


def test_per_endpoint_separation():
    limiter = RateLimiter(rate=0.001, burst=1)
    limiter(make_request(path="/login"))
    limiter(make_request(path="/webhook"))  # different endpoint, separate bucket
    with pytest.raises(HTTPException):
        limiter(make_request(path="/login"))


def test_unknown_client_ip_when_client_is_none():
    limiter = RateLimiter(rate=1, burst=1)
    request = SimpleNamespace(url=SimpleNamespace(path="/x"), client=None)
    # First call passes; no exception even though client is None
    limiter(request)
    with pytest.raises(HTTPException):
        limiter(request)


def test_retry_after_is_positive_integer():
    limiter = RateLimiter(rate=1, burst=1)
    req = make_request()
    limiter(req)
    with pytest.raises(HTTPException) as excinfo:
        limiter(req)
    retry_after = int(excinfo.value.headers["Retry-After"])
    assert retry_after >= 1


def _config_with_proxies(proxies):
    return SimpleNamespace(general=SimpleNamespace(trusted_proxies=proxies))


def test_trust_forwarded_separates_clients_behind_trusted_proxy():
    limiter = RateLimiter(rate=0.001, burst=1, trust_forwarded=True)
    with patch(
        "backend.util.config.load_config",
        return_value=_config_with_proxies(["private"]),
    ):
        limiter(make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.1"}))
        # Different forwarded client gets its own bucket
        limiter(make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.2"}))
        with pytest.raises(HTTPException) as excinfo:
            limiter(
                make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.1"})
            )
        assert excinfo.value.status_code == 429


def test_trust_forwarded_ignores_forged_xff_from_untrusted_peer():
    limiter = RateLimiter(rate=0.001, burst=1, trust_forwarded=True)
    with patch(
        "backend.util.config.load_config",
        return_value=_config_with_proxies(["private"]),
    ):
        limiter(make_request(ip="8.8.8.8", headers={"X-Forwarded-For": "10.0.0.1"}))
        # Rotating XFF must not mint a fresh bucket for an untrusted peer
        with pytest.raises(HTTPException):
            limiter(make_request(ip="8.8.8.8", headers={"X-Forwarded-For": "10.0.0.2"}))


def test_trust_forwarded_falls_back_to_peer_on_config_failure():
    limiter = RateLimiter(rate=0.001, burst=1, trust_forwarded=True)
    with patch(
        "backend.util.config.load_config", side_effect=RuntimeError("config broken")
    ):
        limiter(make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.1"}))
        with pytest.raises(HTTPException):
            limiter(
                make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.2"})
            )


def test_default_ignores_forwarded_headers():
    limiter = RateLimiter(rate=0.001, burst=1)
    limiter(make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.1"}))
    with pytest.raises(HTTPException):
        limiter(make_request(ip="172.16.0.9", headers={"X-Forwarded-For": "10.0.0.2"}))

"""Tests for the webhook_secret minimum-length policy on config saves."""

from backend.api.config import _reject_weak_webhook_secret


def _cfg(secret: str) -> dict:
    return {"general": {"webhook_secret": secret}}


def test_changed_short_secret_rejected():
    msg = _reject_weak_webhook_secret(_cfg(""), _cfg("short"))
    assert msg is not None
    assert "16 characters" in msg


def test_changed_long_secret_accepted():
    assert _reject_weak_webhook_secret(_cfg(""), _cfg("a" * 16)) is None


def test_unchanged_short_secret_accepted():
    assert _reject_weak_webhook_secret(_cfg("short"), _cfg("short")) is None


def test_empty_new_secret_accepted():
    assert _reject_weak_webhook_secret(_cfg("short"), _cfg("")) is None


def test_missing_general_section_accepted():
    assert _reject_weak_webhook_secret({}, {}) is None

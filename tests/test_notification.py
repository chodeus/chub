"""Tests for backend/util/notification.py — payload formatting helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.util.notification import NotificationManager, get_random_joke


def make_manager(config=None):
    return NotificationManager(
        config=config or SimpleNamespace(notifications={}),
        logger=MagicMock(),
        module_name="poster_renamerr",
    )


# --- format_module_title ---


def test_format_module_title():
    assert NotificationManager.format_module_title("poster_renamerr") == "Poster Renamerr"
    assert NotificationManager.format_module_title("nohl") == "Nohl"


# --- _as_dict ---


def test_as_dict_with_none():
    assert NotificationManager._as_dict(None) == {}


def test_as_dict_with_dict():
    assert NotificationManager._as_dict({"a": 1}) == {"a": 1}


def test_as_dict_with_pydantic_like():
    obj = SimpleNamespace(model_dump=lambda mode: {"k": "v"})
    assert NotificationManager._as_dict(obj) == {"k": "v"}


def test_as_dict_with_unsupported_object():
    assert NotificationManager._as_dict("string") == {}
    assert NotificationManager._as_dict(123) == {}


# --- _get_module_config ---


def test_get_module_config_dict():
    cfg = {"poster_renamerr": {"x": 1}, "other": {"y": 2}}
    assert NotificationManager._get_module_config(cfg, "poster_renamerr") == {"x": 1}


def test_get_module_config_namespace_attr():
    cfg = SimpleNamespace(poster_renamerr=SimpleNamespace(x=1))
    out = NotificationManager._get_module_config(cfg, "poster_renamerr")
    assert out.x == 1


def test_get_module_config_falls_back_to_self():
    """If module attr missing on a dict, returns the whole dict."""
    cfg = {"other": {"y": 2}}
    assert NotificationManager._get_module_config(cfg, "missing") == cfg


# --- build_notifiarr_payload ---


def test_build_notifiarr_payload_shape():
    p = NotificationManager.build_notifiarr_payload("Title", 12345)
    assert p["notification"]["name"] == "Title"
    assert p["discord"]["ids"]["channel"] == 12345
    assert p["discord"]["text"]["title"] == "Test Notification"


# --- build_discord_payload ---


def test_build_discord_payload_handles_int_color():
    payloads = NotificationManager.build_discord_payload(
        "Mod",
        [{"embed": True, "fields": [{"name": "f", "value": "v"}]}],
        "2024-01-01T00:00:00Z",
    )
    assert len(payloads) == 1
    assert payloads[0]["embeds"][0]["color"] == 0x00FF00
    assert payloads[0]["embeds"][0]["title"].startswith("Mod")


def test_build_discord_payload_handles_str_color():
    payloads = NotificationManager.build_discord_payload(
        "Mod",
        [{"embed": True, "fields": []}],
        "2024-01-01T00:00:00Z",
        color="FF0000",
    )
    assert payloads[0]["embeds"][0]["color"] == 0xFF0000


def test_build_discord_payload_handles_dict_data():
    """If data is a dict, it's converted to a list of embeds."""
    payloads = NotificationManager.build_discord_payload(
        "Mod",
        {1: [{"name": "f1", "value": "v1"}], 2: [{"name": "f2", "value": "v2"}]},
        "2024-01-01T00:00:00Z",
    )
    assert len(payloads) == 2
    # Multi-part should label parts
    titles = [p["embeds"][0]["title"] for p in payloads]
    assert any("Part" in t for t in titles)


# --- get_random_joke ---


def test_get_random_joke_returns_string():
    # File may or may not exist depending on layout — always returns string
    result = get_random_joke()
    assert isinstance(result, str)


# --- _get_notification_targets ---


def test_notification_targets_returns_module_specific():
    cfg = SimpleNamespace(
        notifications={
            "poster_renamerr": {"discord": {"webhook": "x"}},
            "other": {},
        }
    )
    m = make_manager(cfg)
    assert m._get_notification_targets() == {"discord": {"webhook": "x"}}


def test_notification_targets_returns_top_level_when_service_keys_present():
    """If notifications dict has service keys but no module key, return whole dict."""
    cfg = SimpleNamespace(notifications={"discord": {"webhook": "x"}})
    m = make_manager(cfg)
    assert m._get_notification_targets() == {"discord": {"webhook": "x"}}


def test_notification_targets_empty_when_no_match():
    cfg = SimpleNamespace(notifications={"other_module": {"discord": {}}})
    m = make_manager(cfg)
    assert m._get_notification_targets() == {}

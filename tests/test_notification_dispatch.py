"""Tests for the per-destination notification dispatch resolution.

Covers `NotificationManager._resolve_targets` / `_validate_target` (the new
destination-centric routing) and `install_error_notify_handler`'s
failure-destination detection. The actual HTTP send is not exercised here.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.notification import (  # noqa: E402
    NotificationManager,
    install_error_notify_handler,
)

LOG = logging.getLogger("test.notification")


def _mgr(destinations, module_name="poster_renamerr"):
    config = {"notifications": {"destinations": destinations}}
    return NotificationManager(config, LOG, module_name=module_name)


def _dest(**kw):
    base = {
        "id": "d1",
        "method": "discord",
        "name": "",
        "enabled": True,
        "events": {"success": True, "failure": False},
        "modules": ["__ALL__"],
        "config": {"webhook": "https://discord.com/api/webhooks/1/a"},
    }
    base.update(kw)
    return base


def test_resolve_targets_module_match():
    dests = [
        _dest(id="d1", modules=["poster_renamerr"]),
        _dest(
            id="d2",
            modules=["nohl"],
            config={"webhook": "https://discord.com/api/webhooks/2/b"},
        ),
    ]
    resolved = _mgr(dests)._resolve_targets("success", "poster_renamerr")
    assert len(resolved) == 1
    assert resolved[0][0] == "discord"
    assert resolved[0][1]["webhook"].endswith("1/a")


def test_resolve_targets_all_sentinel_matches_any_module():
    resolved = _mgr([_dest(modules=["__ALL__"])])._resolve_targets(
        "success", "anything_at_all"
    )
    assert len(resolved) == 1


def test_resolve_targets_event_filter():
    # failure-only destination is silent on success and fires on failure.
    dests = [_dest(events={"success": False, "failure": True}, modules=["__ALL__"])]
    m = _mgr(dests, module_name="main")
    assert m._resolve_targets("success", "x") == []
    assert len(m._resolve_targets("failure", "x")) == 1


def test_resolve_targets_disabled_skipped():
    resolved = _mgr([_dest(enabled=False)])._resolve_targets(
        "success", "poster_renamerr"
    )
    assert resolved == []


def test_resolve_targets_invalid_config_skipped():
    # notifiarr without channel_id is invalid → dropped, not raised.
    dests = [
        _dest(
            method="notifiarr",
            config={"webhook": "https://notifiarr.com/api/v1/x"},
        )
    ]
    assert _mgr(dests)._resolve_targets("success", "poster_renamerr") == []


def test_validate_target_notifiarr_channel_id_string_coerced():
    v = _mgr([])._validate_target(
        "notifiarr",
        {"webhook": "https://notifiarr.com/api/v1/x", "channel_id": "123"},
    )
    assert v == {
        "webhook": "https://notifiarr.com/api/v1/x",
        "channel_id": 123,
        "color": None,
    }


def test_validate_target_discord_missing_webhook_is_error_string():
    assert isinstance(_mgr([])._validate_target("discord", {}), str)


def test_install_error_notify_handler_no_failure_dest_returns_none():
    from backend.util.config import ChubConfig, ConfigNotifications

    cfg = ChubConfig()
    cfg.notifications = ConfigNotifications(
        destinations=[_dest(events={"success": True, "failure": False})]
    )
    assert install_error_notify_handler(cfg, LOG) is None


def test_install_error_notify_handler_with_failure_dest_installs():
    from backend.util.config import ChubConfig, ConfigNotifications

    cfg = ChubConfig()
    cfg.notifications = ConfigNotifications(
        destinations=[_dest(events={"success": False, "failure": True})]
    )
    handler = install_error_notify_handler(cfg, LOG)
    try:
        assert handler is not None
    finally:
        if handler is not None:
            logging.getLogger().removeHandler(handler)

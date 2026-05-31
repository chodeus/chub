"""Tests for backend/util/notification.py — payload formatting helpers."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from backend.util.notification import (
    DiscordConfig,
    ErrorNotifyHandler,
    NotifiarrConfig,
    NotificationManager,
    install_error_notify_handler,
)


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


# --- resolve_color: output > config > default ---


def test_resolve_color_output_wins():
    assert (
        NotificationManager.resolve_color({"color": "FF0000"}, "00FF00")
        == "FF0000"
    )


def test_resolve_color_falls_back_to_config():
    assert NotificationManager.resolve_color({}, "FF7300") == "FF7300"


def test_resolve_color_default_when_neither_set():
    assert NotificationManager.resolve_color({}, None) == 0x00FF00


def test_resolve_color_empty_output_color_does_not_override():
    """An empty-string color in output (legacy default) shouldn't beat config."""
    assert NotificationManager.resolve_color({"color": ""}, "FF7300") == "FF7300"


# --- collect_valid_targets: bot_name + color survive into the dispatch dict ---


def _cfg_with_discord(**discord_fields):
    return SimpleNamespace(
        notifications={"poster_renamerr": {"discord": discord_fields}}
    )


def _cfg_with_notifiarr(**fields):
    return SimpleNamespace(
        notifications={"poster_renamerr": {"notifiarr": fields}}
    )


def test_collect_targets_discord_preserves_bot_name_and_color():
    cfg = _cfg_with_discord(
        webhook="https://discord.com/api/webhooks/123/abc",
        bot_name="My Bot",
        color="#5865F2",
    )
    m = make_manager(cfg)
    targets = m.collect_valid_targets()
    assert targets["discord"]["webhook"] == "https://discord.com/api/webhooks/123/abc"
    assert targets["discord"]["bot_name"] == "My Bot"
    assert targets["discord"]["color"] == "#5865F2"


def test_collect_targets_discord_test_path_returns_same_shape_as_prod():
    """Regression: test mode used to convert webhook → apprise URL string, diverging from prod."""
    cfg = _cfg_with_discord(webhook="https://discord.com/api/webhooks/123/abc")
    m = make_manager(cfg)
    prod = m.collect_valid_targets(test=False)
    test = m.collect_valid_targets(test=True)
    assert isinstance(prod["discord"], dict)
    assert isinstance(test["discord"], dict)
    assert prod["discord"]["webhook"] == test["discord"]["webhook"]


def test_collect_targets_notifiarr_preserves_color_and_channel():
    cfg = _cfg_with_notifiarr(
        webhook="https://notifiarr.com/api/v1/notification/passthrough/KEY",
        channel_id="1234567890",
        color="#FF7300",
    )
    m = make_manager(cfg)
    targets = m.collect_valid_targets()
    assert targets["notifiarr"]["channel_id"] == 1234567890
    assert targets["notifiarr"]["color"] == "#FF7300"
    # Notifiarr has no per-notification bot override, so we don't carry bot_name
    # through (the UI form doesn't accept it either).
    assert "bot_name" not in targets["notifiarr"]


# --- build_discord_payload: bot_name reaches the Discord username field ---


def test_build_discord_payload_uses_bot_name():
    payloads = NotificationManager.build_discord_payload(
        "Mod",
        [{"embed": True, "fields": []}],
        "2024-01-01T00:00:00Z",
        bot_name="Cool Bot",
    )
    assert payloads[0]["username"] == "Cool Bot"


def test_build_discord_payload_falls_back_to_default_username():
    payloads = NotificationManager.build_discord_payload(
        "Mod",
        [{"embed": True, "fields": []}],
        "2024-01-01T00:00:00Z",
    )
    assert payloads[0]["username"] == "Notification Bot"


# --- build_notifiarr_payload: no bot override (Notifiarr Passthrough doesn't expose one) ---


def test_build_notifiarr_payload_has_no_bot_block():
    """Notifiarr Passthrough has no documented field for overriding the Discord
    bot username — it's controlled by the user's Custom Bot setup on Notifiarr's
    side. Make sure we don't ship a bogus key Notifiarr will silently ignore."""
    p = NotificationManager.build_notifiarr_payload("T", 1)
    assert "bot" not in p["discord"]


# --- End-to-end send_discord_notification (test=True path uses raw POST) ---


def test_send_discord_test_uses_raw_post_with_bot_name_and_color():
    m = make_manager()
    cfg = DiscordConfig(
        webhook="https://discord.com/api/webhooks/1/tok",
        bot_name="TestBot",
        color="#123456",
    )
    with patch.object(NotificationManager, "safe_post") as post:
        post.return_value = SimpleNamespace(status_code=204, text="")
        ok, _ = m.send_discord_notification(cfg, "Mod", None, test=True)
    assert ok
    post.assert_called_once()
    sent_url, sent_payload = post.call_args.args
    assert sent_url == "https://discord.com/api/webhooks/1/tok"
    assert sent_payload["username"] == "TestBot"
    assert sent_payload["embeds"][0]["color"] == 0x123456


def test_send_discord_prod_uses_config_color_then_output_override():
    """Output color (e.g. red for errors) must beat config color."""
    m = make_manager()
    cfg = DiscordConfig(
        webhook="https://discord.com/api/webhooks/1/tok",
        color="00FF00",
    )
    with patch.object(NotificationManager, "safe_post") as post, patch(
        "backend.util.notification_formatting.format_for_discord",
        return_value=([{"embed": True, "fields": []}], True),
    ):
        post.return_value = SimpleNamespace(status_code=204, text="")
        m.send_discord_notification(cfg, "Mod", {"color": "FF0000"})
    assert post.call_args.args[1]["embeds"][0]["color"] == 0xFF0000


# --- End-to-end send_notifiarr_notification ---


def test_send_notifiarr_test_posts_passthrough_payload_to_webhook():
    m = make_manager()
    cfg = NotifiarrConfig(
        webhook="https://notifiarr.com/api/v1/notification/passthrough/KEY",
        channel_id=42,
    )
    with patch.object(NotificationManager, "safe_post") as post:
        post.return_value = SimpleNamespace(status_code=200, text="")
        ok, _ = m.send_notifiarr_notification(cfg, "Mod", None, test=True)
    assert ok
    sent_url, sent_payload = post.call_args.args
    assert sent_url == "https://notifiarr.com/api/v1/notification/passthrough/KEY"
    assert sent_payload["discord"]["ids"]["channel"] == 42
    assert sent_payload["notification"]["name"] == "Mod"


# --- install_error_notify_handler ---


def teardown_function(_):
    """Strip any ErrorNotifyHandler the tests installed on the root logger."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, ErrorNotifyHandler):
            root.removeHandler(h)


def test_install_error_notify_handler_noop_without_main_target():
    cfg = SimpleNamespace(notifications={})
    assert install_error_notify_handler(cfg) is None
    assert not any(
        isinstance(h, ErrorNotifyHandler) for h in logging.getLogger().handlers
    )


def test_install_error_notify_handler_attaches_when_main_configured():
    cfg = SimpleNamespace(
        notifications={"main": {"discord": {"webhook": "https://discord.com/api/webhooks/1/t"}}}
    )
    handler = install_error_notify_handler(cfg)
    assert isinstance(handler, ErrorNotifyHandler)
    assert handler in logging.getLogger().handlers


def test_install_error_notify_handler_idempotent():
    cfg = SimpleNamespace(
        notifications={"main": {"discord": {"webhook": "https://discord.com/api/webhooks/1/t"}}}
    )
    h1 = install_error_notify_handler(cfg)
    h2 = install_error_notify_handler(cfg)
    assert h1 is h2


# --- Regression: NotificationManager must receive the full ChubConfig, not a
# per-module sub-section. Modules used to pass `self.config` (e.g.
# UpgradinatorrConfig) which has no `notifications` field, so every
# production notification silently no-op'd. ---


def test_send_notification_resolves_targets_from_chubconfig_root():
    from backend.util.config import ChubConfig

    full_config = ChubConfig.model_validate(
        {
            "notifications": {
                "upgradinatorr": {
                    "discord": {
                        "webhook": "https://discord.com/api/webhooks/1/tok",
                        "bot_name": "ChubBot",
                        "color": "00FF00",
                    }
                }
            }
        }
    )

    manager = NotificationManager(full_config, MagicMock(), module_name="upgradinatorr")
    with patch.object(NotificationManager, "safe_post") as post, patch(
        "backend.util.notification_formatting.format_for_discord",
        return_value=([{"embed": True, "fields": []}], True),
    ):
        post.return_value = SimpleNamespace(status_code=204, text="")
        result = manager.send_notification({"anything": "here"})

    assert result["success"] is True
    post.assert_called_once()
    sent_url, _ = post.call_args.args
    assert sent_url == "https://discord.com/api/webhooks/1/tok"


def test_send_notification_silent_noop_when_given_module_subsection():
    """Guard against the historical regression: if a caller passes the
    per-module config (no `.notifications` attribute), targets resolve to
    {} and no post is attempted. This must not raise — it just silently
    sends nothing — which is exactly why the bug went unnoticed."""
    from backend.util.config import ChubConfig

    full_config = ChubConfig.model_validate(
        {
            "notifications": {
                "upgradinatorr": {
                    "discord": {"webhook": "https://discord.com/api/webhooks/1/tok"}
                }
            }
        }
    )
    wrong_config = full_config.upgradinatorr  # what modules used to pass

    manager = NotificationManager(wrong_config, MagicMock(), module_name="upgradinatorr")
    with patch.object(NotificationManager, "safe_post") as post:
        result = manager.send_notification({"anything": "here"})

    post.assert_not_called()
    assert result["success"] is False

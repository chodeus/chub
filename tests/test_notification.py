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
    assert (
        NotificationManager.format_module_title("poster_renamerr") == "Poster Renamerr"
    )
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


# --- destination resolution: _resolve_targets ---


def _cfg_with_destinations(destinations):
    return SimpleNamespace(notifications={"destinations": destinations})


def test_resolve_targets_returns_module_specific():
    cfg = _cfg_with_destinations(
        [
            {
                "id": "d1",
                "method": "discord",
                "enabled": True,
                "events": {"success": True, "failure": False},
                "modules": ["poster_renamerr"],
                "config": {"webhook": "https://discord.com/api/webhooks/1/a"},
            },
            {
                "id": "d2",
                "method": "discord",
                "enabled": True,
                "events": {"success": True, "failure": False},
                "modules": ["nohl"],
                "config": {"webhook": "https://discord.com/api/webhooks/2/b"},
            },
        ]
    )
    resolved = make_manager(cfg)._resolve_targets("success", "poster_renamerr")
    assert [t[1]["webhook"] for t in resolved] == [
        "https://discord.com/api/webhooks/1/a"
    ]


def test_resolve_targets_empty_when_no_module_match():
    cfg = _cfg_with_destinations(
        [
            {
                "id": "d1",
                "method": "discord",
                "enabled": True,
                "events": {"success": True, "failure": False},
                "modules": ["nohl"],
                "config": {"webhook": "https://discord.com/api/webhooks/1/a"},
            }
        ]
    )
    assert make_manager(cfg)._resolve_targets("success", "poster_renamerr") == []


# --- resolve_color: output > config > default ---


def test_resolve_color_output_wins():
    assert NotificationManager.resolve_color({"color": "FF0000"}, "00FF00") == "FF0000"


def test_resolve_color_falls_back_to_config():
    assert NotificationManager.resolve_color({}, "FF7300") == "FF7300"


def test_resolve_color_default_when_neither_set():
    assert NotificationManager.resolve_color({}, None) == 0x00FF00


def test_resolve_color_empty_output_color_does_not_override():
    """An empty-string color in output (legacy default) shouldn't beat config."""
    assert NotificationManager.resolve_color({"color": ""}, "FF7300") == "FF7300"


# --- _validate_target: bot_name + color survive; channel_id coerced ---


def test_validate_target_discord_preserves_bot_name_and_color():
    out = make_manager()._validate_target(
        "discord",
        {
            "webhook": "https://discord.com/api/webhooks/123/abc",
            "bot_name": "My Bot",
            "color": "#5865F2",
        },
    )
    assert out == {
        "webhook": "https://discord.com/api/webhooks/123/abc",
        "bot_name": "My Bot",
        "color": "#5865F2",
    }


def test_validate_target_notifiarr_coerces_channel_id_and_omits_bot_name():
    out = make_manager()._validate_target(
        "notifiarr",
        {
            "webhook": "https://notifiarr.com/api/v1/notification/passthrough/KEY",
            "channel_id": "1234567890",
            "color": "#FF7300",
        },
    )
    assert out["channel_id"] == 1234567890
    assert out["color"] == "#FF7300"
    # Notifiarr has no per-notification bot override, so we don't carry bot_name
    # through (the UI form doesn't accept it either).
    assert "bot_name" not in out


def test_validate_target_invalid_returns_error_string():
    m = make_manager()
    assert isinstance(m._validate_target("discord", {}), str)
    assert isinstance(m._validate_target("notifiarr", {"webhook": "x"}), str)


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
    with (
        patch.object(NotificationManager, "safe_post") as post,
        patch(
            "backend.util.notification_formatting.format_for_discord",
            return_value=([{"embed": True, "fields": []}], True),
        ),
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


def _failure_dest_cfg():
    return SimpleNamespace(
        notifications={
            "destinations": [
                {
                    "id": "e1",
                    "method": "discord",
                    "enabled": True,
                    "events": {"success": False, "failure": True},
                    "modules": ["__ALL__"],
                    "config": {"webhook": "https://discord.com/api/webhooks/1/t"},
                }
            ]
        }
    )


def test_install_error_notify_handler_noop_without_failure_target():
    cfg = SimpleNamespace(notifications={"destinations": []})
    assert install_error_notify_handler(cfg) is None
    assert not any(
        isinstance(h, ErrorNotifyHandler) for h in logging.getLogger().handlers
    )


def test_install_error_notify_handler_noop_when_only_success_targets():
    cfg = SimpleNamespace(
        notifications={
            "destinations": [
                {
                    "id": "d1",
                    "method": "discord",
                    "enabled": True,
                    "events": {"success": True, "failure": False},
                    "modules": ["__ALL__"],
                    "config": {"webhook": "https://discord.com/api/webhooks/1/t"},
                }
            ]
        }
    )
    assert install_error_notify_handler(cfg) is None


def test_install_error_notify_handler_attaches_when_failure_configured():
    handler = install_error_notify_handler(_failure_dest_cfg())
    assert isinstance(handler, ErrorNotifyHandler)
    assert handler in logging.getLogger().handlers


def test_install_error_notify_handler_idempotent():
    cfg = _failure_dest_cfg()
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
                "destinations": [
                    {
                        "id": "u1",
                        "method": "discord",
                        "enabled": True,
                        "events": {"success": True, "failure": False},
                        "modules": ["upgradinatorr"],
                        "config": {
                            "webhook": "https://discord.com/api/webhooks/1/tok",
                            "bot_name": "ChubBot",
                            "color": "00FF00",
                        },
                    }
                ]
            }
        }
    )

    manager = NotificationManager(full_config, MagicMock(), module_name="upgradinatorr")
    with (
        patch.object(NotificationManager, "safe_post") as post,
        patch(
            "backend.util.notification_formatting.format_for_discord",
            return_value=([{"embed": True, "fields": []}], True),
        ),
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
    [] and no post is attempted. This must not raise — it just silently
    sends nothing — which is exactly why the bug went unnoticed."""
    from backend.util.config import ChubConfig

    full_config = ChubConfig.model_validate(
        {
            "notifications": {
                "destinations": [
                    {
                        "id": "u1",
                        "method": "discord",
                        "enabled": True,
                        "events": {"success": True, "failure": False},
                        "modules": ["upgradinatorr"],
                        "config": {"webhook": "https://discord.com/api/webhooks/1/tok"},
                    }
                ]
            }
        }
    )
    wrong_config = full_config.upgradinatorr  # what modules used to pass

    manager = NotificationManager(
        wrong_config, MagicMock(), module_name="upgradinatorr"
    )
    with patch.object(NotificationManager, "safe_post") as post:
        result = manager.send_notification({"anything": "here"})

    post.assert_not_called()
    assert result["success"] is False


def test_validate_target_rejects_redacted_placeholder_webhook():
    """A webhook that is the redacted '********' placeholder (or any non-URL)
    must be rejected, not sent — otherwise dispatch hits the SSRF guard every run
    and notifications silently fail."""
    m = make_manager()
    assert isinstance(m._validate_target("discord", {"webhook": "********"}), str)
    assert isinstance(
        m._validate_target("discord", {"webhook": "discord.com/api/webhooks/1/x"}), str
    )
    assert isinstance(
        m._validate_target("notifiarr", {"webhook": "********", "channel_id": 5}), str
    )
    # a real https webhook still validates
    ok = m._validate_target(
        "discord", {"webhook": "https://discord.com/api/webhooks/1/x"}
    )
    assert isinstance(ok, dict) and ok["webhook"].startswith("https://")


# --- 429 rate-limit handling: honour retry_after instead of dropping the part ---


def _resp(status=429, retry_after=None, header=None, text="", raise_json=False):
    """Build a fake webhook response for the send path."""

    def _json():
        if raise_json:
            raise ValueError("no json body")
        return {} if retry_after is None else {"retry_after": retry_after}

    headers = {}
    if header is not None:
        headers["Retry-After"] = header
    return SimpleNamespace(status_code=status, json=_json, headers=headers, text=text)


def test_send_and_log_retries_on_429_then_succeeds():
    m = make_manager()
    seq = [_resp(429, retry_after=0.2), _resp(429, retry_after=0.2), _resp(204)]
    with (
        patch.object(NotificationManager, "safe_post", side_effect=seq) as post,
        patch("backend.util.notification.time.sleep") as sleep,
    ):
        ok, _ = m.send_and_log_response("Discord", "https://h", {"a": 1})
    assert ok is True
    assert post.call_count == 3  # two 429s, then the 204
    assert sleep.call_count == 2
    # honoured the returned retry_after (0.2s) plus the small buffer
    assert abs(sleep.call_args_list[0].args[0] - 0.45) < 1e-6


def test_send_and_log_gives_up_after_max_429():
    m = make_manager()
    with (
        patch.object(
            NotificationManager, "safe_post", return_value=_resp(429, retry_after=0.1)
        ) as post,
        patch("backend.util.notification.time.sleep"),
    ):
        ok, _ = m.send_and_log_response("Discord", "https://h", {"a": 1})
    assert ok is False
    assert post.call_count == NotificationManager._MAX_RATE_LIMIT_RETRIES + 1


def test_retry_after_seconds_prefers_body_then_header_and_clamps():
    # Discord's JSON retry_after (seconds) wins, plus a small buffer.
    assert (
        abs(NotificationManager._retry_after_seconds(_resp(retry_after=1.5)) - 1.75)
        < 1e-6
    )
    # Falls back to the standard Retry-After header.
    assert (
        abs(NotificationManager._retry_after_seconds(_resp(header="2")) - 2.25) < 1e-6
    )
    # An absurd wait is clamped so a global limit can't hang the worker.
    assert NotificationManager._retry_after_seconds(_resp(retry_after=999)) == 30.25
    # Unreadable body + no header → sane default.
    assert NotificationManager._retry_after_seconds(_resp(raise_json=True)) == 1.25


def test_safe_post_passes_timeout(monkeypatch):
    """A hung webhook must not stall the run — every POST is bounded."""
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["timeout"] = timeout
        return SimpleNamespace(status_code=204, text="")

    monkeypatch.setattr("backend.util.notification.requests.post", fake_post)
    monkeypatch.setattr("backend.util.ssrf_guard.is_safe_url", lambda u: (True, ""))
    NotificationManager.safe_post("https://discord.com/api/webhooks/1/x", {"a": 1})
    assert seen["timeout"] == 15


# --- summary collapse: huge runs don't fan out into dozens of Discord messages ---


def _poster_output(n):
    return {
        "movie": [
            {
                "title": f"Movie {i}",
                "year": 2001,
                "messages": [f"poster {i}.jpg -renamed-> {i}.jpg"],
            }
            for i in range(n)
        ]
    }


def test_format_for_discord_caps_bulk_renames():
    """A bulk run is capped to NOTIFICATION_ITEM_CAP items plus a tally — the
    rest stays in the server log rather than flooding the webhook."""
    from backend.util.notification_formatting import (
        NOTIFICATION_ITEM_CAP,
        format_for_discord,
    )

    cfg = SimpleNamespace(module_name="poster_renamerr")
    data, ok = format_for_discord(cfg, _poster_output(400))
    assert ok
    assert len(data) <= 2  # would have been 400 fields before capping
    values = " ".join(f.get("value", "") for fields in data.values() for f in fields)
    assert "400 movies renamed" in values  # the tally is always present
    assert "Movie 0 (2001)" in values
    assert f"Movie {NOTIFICATION_ITEM_CAP} (2001)" not in values  # past the cap
    assert f"and {400 - NOTIFICATION_ITEM_CAP} more" in values
    assert "see the server log" in values


def test_format_for_discord_collapses_huge_run():
    """The rate-limit backstop still fires for a formatter that emits many
    sections, even though each section is individually capped."""
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="labelarr")
    payload = [
        {"title": f"T{i}", "year": 2001, "add_remove": {f"label{i}": "add"}}
        for i in range(400)
    ]
    data, ok = format_for_discord(cfg, payload)
    assert ok
    assert len(data) == 1  # collapsed to a single summary embed
    assert "collapsed" in data[1][0]["value"].lower()


def test_format_for_discord_keeps_small_run_detailed():
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="poster_renamerr")
    data, ok = format_for_discord(cfg, _poster_output(5))
    assert ok
    values = " ".join(f.get("value", "") for fields in data.values() for f in fields)
    assert "5 movies renamed" in values  # tally accompanies the detail
    assert "Movie 0 (2001)" in values  # per-item detail preserved
    assert "poster 0.jpg -renamed-> 0.jpg" in values
    assert "see the server log" not in values  # nothing truncated under the cap
    names = [f.get("name", "") for fields in data.values() for f in fields]
    assert not any("items processed" in n for n in names)  # not summarised


def test_format_for_discord_empty_text_override():
    """The plex upload path replaces the default 'No files were renamed.'
    heartbeat with an upload-accurate line via the empty_text key."""
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="poster_renamerr")
    data, ok = format_for_discord(
        cfg,
        {
            "collection": [],
            "movie": [],
            "show": [],
            "empty_text": "No posters were uploaded (nothing changed).",
        },
    )
    assert ok
    fields = data[1]
    assert fields[0]["name"] == "No posters were uploaded (nothing changed)."


def test_format_for_discord_empty_default_unchanged():
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="poster_renamerr")
    data, _ = format_for_discord(cfg, {"collection": [], "movie": [], "show": []})
    assert data[1][0]["name"] == "No files were renamed."


def test_format_for_discord_renders_artist_and_album():
    """Music uploads must render, not silently fall through to the empty
    heartbeat (artist/album previously weren't handled by the formatter)."""
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="poster_renamerr")
    data, _ = format_for_discord(
        cfg,
        {
            "artist": [{"title": "Queen", "year": None, "messages": ["Uploaded to Music"]}],
            "album": [
                {
                    "title": "Greatest Hits",
                    "year": 1981,
                    "messages": ["Uploaded to Music"],
                }
            ],
        },
    )
    values = " ".join(f.get("value", "") for fields in data.values() for f in fields)
    assert "Queen" in values
    assert "Greatest Hits (1981)" in values
    names = [f.get("name", "") for fields in data.values() for f in fields]
    assert not any("No files were renamed" in n for n in names)


# --- notifications carry summaries, not the run log's debug detail ---


def _upgradinatorr_output():
    return {
        "lidarr_main": {
            "server_name": "Lidarr (Music)",
            "data": [
                {
                    "title": "Anastacia",
                    "year": None,
                    "download": {"Anastacia - Resurrection": 250},
                    "queue_imports": [],
                },
                {
                    "title": "Armin van Buuren",
                    "year": None,
                    "download": {},
                    "queue_imports": [
                        {
                            "state": "pending",
                            "download": "Armin van Buuren - Starbound [WEB] [FLAC]",
                            "age_hours": 40.0,
                            "messages": [
                                "One or more tracks expected in this release "
                                "were not imported or missing from the release",
                                "Has unmatched tracks",
                            ],
                        }
                    ],
                },
            ],
        }
    }


def test_upgradinatorr_notification_tallies_the_queue():
    """The *arr's own rejection text and the per-item queue rows are log-level
    detail — the notification carries only the section tally."""
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="upgradinatorr")
    data, ok = format_for_discord(cfg, _upgradinatorr_output())
    assert ok
    blob = " ".join(
        f.get("name", "") + " " + f.get("value", "")
        for fields in data.values()
        for f in fields
    )
    # The grab is what the run changed — it stays.
    assert "Anastacia - Resurrection" in blob
    # The queue section collapses to the same tally the run log prints.
    assert "1 download(s) across 1 item(s)" in blob
    assert "already downloaded, not searched again" in blob
    # None of the per-item queue detail may reach Discord.
    assert "Has unmatched tracks" not in blob
    assert "not imported or missing" not in blob
    assert "waiting 40h" not in blob
    assert "Starbound" not in blob


def test_upgradinatorr_notification_matches_the_log_tally():
    """One owner for the section policy: the notification's tally string is the
    same helper the run log renders, so the two can't drift again."""
    from backend.util.constants import QUEUE_REPORT_SECTIONS, queue_report_tally
    from backend.util.notification_formatting import format_for_discord

    cfg = SimpleNamespace(module_name="upgradinatorr")
    data, ok = format_for_discord(cfg, _upgradinatorr_output())
    assert ok
    _state, _tag, note, _level = QUEUE_REPORT_SECTIONS[0]
    expected = queue_report_tally(1, 1, note)
    values = " ".join(f.get("value", "") for fields in data.values() for f in fields)
    assert expected in values

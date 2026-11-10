"""Pins that exception text stays in the log; each path here once sent it to the browser."""

import json
import os
import sqlite3
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.api import media_api, system
from backend.util import public_error
from backend.util.notification import NotificationManager
from backend.util.poster_self_heal import apply as heal_apply

from tests.test_asset_renamerr import _make_src, _media, make_module

# What a real exception carries: a path, a host and a credential.
_SECRET = "/srv/media/x.jpg via https://hooks.example/abc?token=hunter2"
_HOOK = "https://discord.com/api/webhooks/1/a"


@pytest.mark.parametrize(
    "exc, reason",
    [
        (requests.exceptions.ConnectTimeout(_SECRET), "timed out"),
        (requests.exceptions.ConnectionError(_SECRET), "could not connect"),
        (requests.exceptions.HTTPError(_SECRET), "request failed"),
        (PermissionError(13, _SECRET), "permission denied"),
        (FileNotFoundError(2, _SECRET), "not found"),
        (NotADirectoryError(20, _SECRET), "not a folder"),
        (TimeoutError(_SECRET), "timed out"),
        (OSError(5, _SECRET), "system error"),
        (RuntimeError(_SECRET), "unexpected error"),
    ],
)
def test_the_reason_names_the_kind_of_failure_only(exc, reason):
    assert public_error.public_reason(exc) == reason
    text = public_error.failure_text("file op", exc)
    assert text == f"file op failed: {reason} — see the server log"
    assert "hunter2" not in text


def _manager():
    return NotificationManager(
        config=SimpleNamespace(notifications={}),
        logger=MagicMock(),
        module_name="poster_renamerr",
    )


def test_a_failed_send_returns_no_traceback():
    manager = _manager()
    boom = RuntimeError(_SECRET)
    with patch.object(NotificationManager, "safe_post", side_effect=boom):
        ok, message = manager.send_and_log_response("Discord", _HOOK, {"a": 1})

    assert ok is False
    assert message == "Discord send failed: unexpected error — see the server log"
    logged = " ".join(str(call) for call in manager.logger.error.call_args_list)
    assert "hunter2" in logged


def test_a_failed_test_notification_returns_no_traceback():
    manager = _manager()
    boom = RuntimeError(_SECRET)
    with patch.object(NotificationManager, "send_discord_notification", side_effect=boom):
        result = manager.send_test_to("discord", {"webhook": _HOOK})

    expected = "Testing discord failed: unexpected error — see the server log"
    assert result["success"] is False
    assert result["error"] == expected
    assert result["results"][0]["message"] == expected
    assert manager.logger.error.called


def test_a_failed_run_notification_returns_no_traceback(monkeypatch):
    manager = _manager()
    targets = [("discord", {"webhook": _HOOK})]
    monkeypatch.setattr(manager, "_resolve_targets", lambda event, module: targets)

    def boom(*args, **kwargs):
        raise RuntimeError(_SECRET)

    manager.SEND_HANDLERS["discord"] = boom
    result = manager.send_notification({"x": 1})

    expected = "Sending to discord failed: unexpected error — see the server log"
    assert result["error"] == expected


def test_a_failed_asset_file_op_keeps_the_reason_in_the_log(tmp_path, monkeypatch):
    dest = tmp_path / "assets"
    dest.mkdir()
    module = make_module(
        apply_method="kometa",
        action_type="copy",
        asset_folders=False,
        destination_dir=str(dest),
    )

    def denied(*args, **kwargs):
        raise PermissionError(13, _SECRET)

    monkeypatch.setattr(module, "_file_op", denied)
    src = _make_src(tmp_path)
    applied, detail = module._apply_kometa(_media(), "logo", "local", src, None)

    assert applied is False
    assert detail == "file op failed: permission denied — see the server log"


def test_a_failed_cache_delete_keeps_the_reason_in_the_log():
    def boom(rid):
        raise sqlite3.OperationalError(_SECRET)

    media = types.SimpleNamespace(get_by_id=lambda rid: {"id": rid}, delete_by_id=boom)
    db = types.SimpleNamespace(media=media)
    logger = MagicMock()

    removed, reason = media_api._remove_media_item(db, logger, 7, False, False)

    assert removed is False
    assert reason == "cache delete failed: unexpected error — see the server log"
    assert "hunter2" in str(logger.error.call_args)


def test_an_unreadable_mount_reports_only_the_kind(monkeypatch):
    # Faked for CHUB's mounts only: pytest itself stats files to report a failure.
    mounts = {"/config", "/kometa", "/media", "/plex", "/data"}
    real_isdir, real_stat = os.path.isdir, os.stat
    monkeypatch.setattr(
        system.os.path, "isdir", lambda p: p == "/data" if p in mounts else real_isdir(p)
    )

    def denied(path, *args, **kwargs):
        if path == "/data":
            raise PermissionError(13, _SECRET)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(system.os, "stat", denied)
    logger = MagicMock()

    response = system.system_disk(logger=logger)

    entries = json.loads(response.body)["data"]["mounts"]
    entry = next(m for m in entries if m["path"] == "/data")
    assert entry["error"] == "permission denied"
    assert "hunter2" in str(logger.warning.call_args)


def test_a_failed_local_rename_note_holds_no_path(tmp_path, monkeypatch):
    old = tmp_path / "Old (2020).jpg"
    old.write_bytes(b"x")
    row = {
        "current_filename": old.name,
        "proposed_filename": "New (2020).jpg",
        "poster_file": str(old),
        "drive_folder_id": None,
    }

    def denied(src, dst):
        raise PermissionError(13, _SECRET)

    monkeypatch.setattr(heal_apply.os, "replace", denied)
    note = heal_apply.apply_proposal(row, None, MagicMock())

    assert note == (
        " (local rename failed: permission denied — see the server log; "
        "it will refresh on the next scan)"
    )
    assert os.path.exists(old)

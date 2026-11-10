"""Pins that exception text stays in the log; each path here once sent it to the browser."""

import errno
import json
import os
import sqlite3
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pydantic
import pytest
import requests

from backend.api import media_api, system
from backend.util import public_error
from backend.util import webhook_provisioner as wp
from backend.util.connector import Connector, InstanceConfig
from backend.util.module_orchestrator import ModuleOrchestrator
from backend.util.notification import NotificationManager
from backend.util.poster_self_heal import apply as heal_apply
from backend.util.upload_posters import PosterUploader

from tests.test_asset_renamerr import _make_src, _media, make_module
from tests.test_webhook_provisioner import _fake_config

# What a real exception carries: a path, a host and a credential.
_SECRET = "/srv/media/x.jpg via https://hooks.example/abc?token=hunter2"
_HOOK = "https://discord.com/api/webhooks/1/a"



class _Model(pydantic.BaseModel):
    webhook: int


def _validation_error():
    try:
        _Model(webhook=_SECRET)
    except pydantic.ValidationError as exc:
        return exc
    raise AssertionError("no ValidationError")


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
        (OSError(errno.EXDEV, _SECRET), "cross-device link"),
        (OSError(errno.ENOSPC, _SECRET), "disk full"),
        (OSError(errno.EROFS, _SECRET), "read-only file system"),
        (_validation_error(), "invalid settings"),
        (sqlite3.OperationalError(_SECRET), "database busy or unavailable"),
        (sqlite3.IntegrityError(_SECRET), "database error"),
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
    assert reason == "cache delete failed: database busy or unavailable — see the server log"
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


class _RaisingArr:
    """An arr client that connects, then raises on the first real call."""

    session = None

    def is_connected(self):
        return True

    def get_notifications(self):
        raise RuntimeError(_SECRET)


def test_a_failed_webhook_setup_reports_only_the_kind(monkeypatch):
    monkeypatch.setattr(wp, "create_arr_client", lambda url, api, logger: _RaisingArr())
    logger = MagicMock()

    rows = wp.provision_all(_fake_config(), "http://chub:8060", None, logger=logger)

    radarr = next(r for r in rows if r["name"] == "Radarr")
    assert radarr["status"] == "failed"
    assert radarr["error"] == (
        "The request to the instance failed: unexpected error — see the server log"
    )
    assert "hunter2" in str(logger.warning.call_args_list)


def test_a_failed_arr_sync_reports_only_the_kind():
    connector = object.__new__(Connector)

    def boom(config):
        raise RuntimeError(_SECRET)

    connector.connection_manager = SimpleNamespace(get_arr_client=boom)
    logger = MagicMock()
    instance = InstanceConfig(name="Radarr", type="radarr", url="http://r", api_key="k")

    result = connector._sync_single_arr_instance(instance, logger)

    assert result.success is False
    assert result.error_message == "Sync failed: unexpected error — see the server log"
    assert "hunter2" in str(logger.warning.call_args)


def test_a_module_that_raises_reports_only_the_kind(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError(_SECRET)

    db = SimpleNamespace(worker=SimpleNamespace(enqueue_job=boom))
    orchestrator = ModuleOrchestrator(logger=MagicMock(), db=db)
    monkeypatch.setattr("backend.util.config.module_is_disabled", lambda name: False)

    result = orchestrator.run_module_immediate("nohl", "web")

    assert result["success"] is False
    assert result["message"] == (
        "Running the module failed: unexpected error — see the server log"
    )


def test_a_failed_enqueue_reports_no_worker_text(monkeypatch):
    worker = SimpleNamespace(
        enqueue_job=lambda **kwargs: {
            "success": False,
            "message": f"Error enqueuing job: {_SECRET}",
        }
    )
    orchestrator = ModuleOrchestrator(logger=MagicMock(), db=SimpleNamespace(worker=worker))
    monkeypatch.setattr("backend.util.config.module_is_disabled", lambda name: False)

    result = orchestrator.run_module_async("nohl", origin="web")

    assert result == {
        "success": False,
        "message": "Failed to enqueue nohl — see the server log",
        "error_code": "ENQUEUE_FAILED",
    }


def _boom(*args, **kwargs):
    raise RuntimeError(_SECRET)


def _uploader():
    uploader = object.__new__(PosterUploader)
    uploader.logger = MagicMock()
    uploader._plex_clients, uploader._media_indexes = {}, {}
    uploader.manifest = {}
    return uploader


@pytest.mark.parametrize(
    "method, extra",
    [
        ("_sync_movies", ()),
        ("_sync_series", ()),
        ("_sync_seasons", ({},)),
        ("_sync_collections", ()),
        ("_sync_artists", ()),
        ("_sync_albums", ()),
    ],
)
def test_a_failed_poster_item_reports_only_the_kind(method, extra, monkeypatch):
    uploader = _uploader()
    monkeypatch.setattr(uploader, "_sync_single_asset", _boom)
    item = {"title": "T", "asset_type": "movie", "season_number": 1}

    [result] = getattr(uploader, method)([item], None, {}, *extra, False)

    assert result.reason == "Processing failed: unexpected error — see the server log"


def test_a_failed_poster_match_reports_only_the_kind(monkeypatch):
    uploader = _uploader()
    monkeypatch.setattr(uploader, "match_asset", _boom)
    asset = {"title": "T", "asset_type": "movie", "renamed_file": "/x.jpg"}

    result = uploader._sync_single_asset(asset, None, {}, ["tmdb"], False)

    assert result.reason == "Processing failed: unexpected error — see the server log"


def test_a_failed_poster_upload_run_reports_only_the_kind(monkeypatch):
    uploader = _uploader()
    monkeypatch.setattr(uploader, "_get_enabled_instances", _boom)

    result = uploader.run()

    assert result["message"] == "Poster upload failed: unexpected error — see the server log"


def test_a_failed_poster_instance_reports_only_the_kind():
    uploader = _uploader()
    plex = SimpleNamespace(get=_boom)
    uploader.full_config = SimpleNamespace(instances=SimpleNamespace(plex=plex))

    result = uploader._process_instance("plex", ["Movies"])

    assert result.error_message == (
        "Instance plex failed: unexpected error — see the server log"
    )


def test_a_failed_plex_mapping_update_reports_only_the_kind():
    connector = object.__new__(Connector)
    connector.logger = None
    connector.connection_manager = SimpleNamespace(close_all_connections=lambda: None)
    connector.update_arr_database = lambda: []
    connector.update_plex_database = lambda: []
    connector.update_collections_database = lambda: []
    connector.update_media_plex_mappings = _boom

    results = connector.sync_all_databases()

    assert results["mappings"] == {
        "error": "Plex mapping update failed: unexpected error — see the server log"
    }


def test_an_unreadable_config_refuses_with_only_the_kind(monkeypatch):
    from backend.util.connector import resolve_instance_names

    monkeypatch.setattr("backend.util.config.load_config", _boom)
    logger = MagicMock()

    names, refusal = resolve_instance_names(None, logger, ["Radarr"], "the scan")

    assert names == []
    assert refusal == (
        "Cannot load the config to check the instances for the scan "
        "(unexpected error) — see the server log."
    )
    assert "hunter2" in str(logger.error.call_args)


def test_a_module_that_cannot_be_queued_reports_only_the_kind(monkeypatch):
    db = SimpleNamespace(worker=SimpleNamespace(enqueue_job=_boom))
    orchestrator = ModuleOrchestrator(logger=MagicMock(), db=db)
    monkeypatch.setattr("backend.util.config.module_is_disabled", lambda name: False)

    result = orchestrator.run_module_async("nohl", origin="web")

    assert result["message"] == (
        "Queueing the module failed: unexpected error — see the server log"
    )


def test_a_failed_auto_apply_stores_only_the_kind(monkeypatch):
    from backend.modules import poster_self_heal as heal_module

    monkeypatch.setattr(heal_module, "apply_proposal", _boom)
    module = object.__new__(heal_module.PosterSelfHeal)
    module.logger = MagicMock()
    prop = {"current_filename": "Old.jpg", "proposed_filename": "New.jpg", "status": "proposed"}

    error = module._auto_apply(prop, None)

    assert error == "Auto-apply failed: unexpected error — see the server log"
    assert prop["status"] == "proposed"
    assert "hunter2" in str(module.logger.warning.call_args)


def test_a_failed_webhook_enqueue_returns_no_worker_text(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api import webhooks

    monkeypatch.setattr(
        webhooks, "load_config",
        lambda: SimpleNamespace(general=SimpleNamespace(trusted_proxies=[])),
    )
    monkeypatch.setattr(webhooks, "_is_duplicate_webhook", lambda *a, **k: False)
    monkeypatch.setattr(webhooks, "_webhook_dedup_identity", lambda *a, **k: None)
    worker = SimpleNamespace(
        enqueue_job=lambda *a, **k: {"success": False, "message": _SECRET, "status": 503}
    )
    app = FastAPI()
    app.state.logger = MagicMock()
    app.state.db = SimpleNamespace(worker=worker)
    app.dependency_overrides[webhooks.verify_webhook_secret] = lambda: None
    app.include_router(webhooks.router)

    resp = TestClient(app).post("/api/webhooks/poster/add", json={"eventType": "Download"})

    assert resp.status_code == 503
    assert resp.json()["message"] == "Error enqueuing webhook"
    assert "hunter2" not in resp.text


def test_failed_module_stats_return_no_worker_text():
    from backend.api import modules

    db = SimpleNamespace(
        worker=SimpleNamespace(job_stats=lambda: {"success": False, "message": _SECRET}),
        run_state=SimpleNamespace(get_all=lambda: []),
    )

    resp = modules.get_modules_stats(module=None, logger=MagicMock(), db=db)

    assert resp.status_code == 500
    assert "hunter2" not in resp.body.decode()


# --- CHUB's own errors carry a fixed phrase; the deepest known cause wins ---


def _raised(exc, cause=None):
    try:
        try:
            if cause is not None:
                raise cause
        except BaseException as inner:
            raise exc from inner
        raise exc
    except BaseException as caught:
        return caught


def test_the_deepest_known_cause_names_the_failure():
    from backend.util.arr import ARRAuthenticationError
    from backend.util.connector import ConnectionPoolError, ConnectorError, DatabaseSyncError

    wrapped_auth = _raised(ConnectionPoolError("pool"), ARRAuthenticationError(_SECRET))
    wrapped_timeout = _raised(
        ConnectionPoolError("pool"), requests.exceptions.ConnectTimeout(_SECRET)
    )
    wrapped_db = _raised(DatabaseSyncError("sync"), sqlite3.OperationalError(_SECRET))
    wrapped_os = _raised(RuntimeError(_SECRET), OSError(5, _SECRET))

    assert public_error.public_reason(wrapped_auth) == "unauthorized: check the API key"
    assert public_error.public_reason(wrapped_timeout) == "timed out"
    assert public_error.public_reason(wrapped_db) == "database busy or unavailable"
    assert public_error.public_reason(wrapped_os) == "system error"
    assert public_error.public_reason(ConnectorError(_SECRET)) == "sync error"


def test_a_missing_rclone_says_so(monkeypatch):
    from backend.util.cl2k import gdrive_upload

    monkeypatch.setenv("RCLONE_PATH", "/nonexistent/rclone")
    with pytest.raises(FileNotFoundError) as caught:
        gdrive_upload._rclone_path()

    assert public_error.public_reason(caught.value) == "rclone is not installed"


def test_a_drive_name_collision_is_stored_as_a_refusal(monkeypatch):
    from backend.modules import poster_self_heal as heal_module

    monkeypatch.setattr(heal_apply, "list_files", lambda *a, **k: ["New.jpg"])
    module = object.__new__(heal_module.PosterSelfHeal)
    module.logger = MagicMock()
    prop = {
        "current_filename": "Old.jpg",
        "proposed_filename": "New.jpg",
        "drive_folder_id": "FOLDER",
        "poster_file": "",
        "status": "proposed",
    }

    error = module._auto_apply(prop, None)

    assert error == (
        "Auto-apply failed: the new name is already taken in the Drive folder "
        "— see the server log"
    )


def test_a_blocked_test_notification_says_why():
    """Through the real SSRF guard: an IP literal is refused before any lookup."""
    result = _manager().send_test_to("discord", {"webhook": "http://169.254.169.254/hook"})

    assert result["error"] == (
        "Discord send failed: the URL was refused (private or unresolvable host) "
        "— see the server log"
    )


def test_a_failed_webhook_update_keeps_what_the_row_found(monkeypatch):
    from backend.util.arr import ARRPermanentError

    from tests.test_webhook_provisioner import StubClient, _existing

    class _GoneOnPut(StubClient):
        def update_notification(self, notification_id, body, force_save=False):
            raise ARRPermanentError(f"Endpoint not found: {_SECRET}")

    foreign = {
        "id": 9,
        "name": "Other hook",
        "implementation": "Webhook",
        "onMovieAdded": True,
        "fields": [{"name": "url", "value": "http://x/api/webhooks/poster/add"}],
    }
    client = _GoneOnPut(notifications=[_existing("http://old/url"), foreign])
    monkeypatch.setattr(wp, "create_arr_client", lambda url, api, logger: client)

    rows = wp.provision_all(_fake_config(), "http://chub:8060", None, logger=MagicMock())

    radarr = next(r for r in rows if r["name"] == "Radarr")
    assert radarr["error"] == (
        "The request to the instance failed: the instance rejected the request "
        "— see the server log"
    )
    assert radarr["drift_fields"]
    assert radarr["foreign_webhook"] == "Other hook"


@pytest.fixture
def chub_db(tmp_path):
    from backend.util.database import ChubDB

    log = SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: log,
    )
    with ChubDB(log, db_path=str(tmp_path / "chub.db")) as database:
        yield database


def test_a_failed_job_stats_read_leaks_nowhere(chub_db, monkeypatch):
    from backend.api import modules

    real = chub_db.worker.execute_query

    def flaky(query, *args, **kwargs):
        if "GROUP BY status" in query:
            raise sqlite3.OperationalError(_SECRET)
        return real(query, *args, **kwargs)

    monkeypatch.setattr(chub_db.worker, "execute_query", flaky)

    assert chub_db.worker.job_stats()["message"] == (
        "Fetching job stats failed: database busy or unavailable — see the server log"
    )
    resp = modules.get_module_specific_stats(name="nohl", logger=MagicMock(), db=chub_db)
    assert resp.status_code == 500
    assert "hunter2" not in resp.body.decode()


def test_a_failed_drive_sync_enqueue_is_not_reported_as_started(monkeypatch):
    from backend.api.posters import gdrive

    folders = [SimpleNamespace(name="Movies")]
    monkeypatch.setattr(
        gdrive,
        "SyncGDrive",
        lambda logger: SimpleNamespace(config=SimpleNamespace(gdrive_list=folders)),
    )
    worker = SimpleNamespace(
        enqueue_job=lambda *a, **k: {"success": False, "message": _SECRET}
    )

    resp = gdrive.sync_gdrive_folders(
        gdrive_names=["Movies"], logger=MagicMock(), db=SimpleNamespace(worker=worker)
    )

    assert resp.status_code == 500
    assert json.loads(resp.body)["message"] == "Error starting the GDrive sync"

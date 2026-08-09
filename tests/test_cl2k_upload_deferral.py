"""Artwork and posters must defer Drive uploads the same way, and a deferred
failure must be reported.

Before this, only the poster path deferred; the three asset makers uploaded
inline. That inconsistency was benign on its own — but a deferred upload has no
response left to fail on, so the caller is told "queued" and a later failure
existed only as a log line. Aligning the paths without also reporting failures
would have spread that silence to artwork.
"""

import types

import pytest

pytest.importorskip("wand.image")  # backend.api.cl2k_maker pulls in the renderer

import backend.api.cl2k_maker as cl2k_api  # noqa: E402
import backend.modules.cl2k_maker as maker  # noqa: E402

ARTWORK_ENDPOINTS = ("square_generate", "background_generate", "logo_asset_generate")


def test_every_interactive_save_endpoint_takes_background_tasks():
    """The defer wiring must reach all four, not just the poster path."""
    import inspect

    for name in ("generate",) + ARTWORK_ENDPOINTS:
        params = inspect.signature(getattr(cl2k_api, name)).parameters
        assert "background_tasks" in params, f"{name} cannot defer"


def test_every_generator_accepts_defer_upload():
    import inspect

    for name in (
        "generate_for_item",
        "generate_square_art",
        "generate_background_art",
        "generate_logo_asset",
    ):
        params = inspect.signature(getattr(maker, name)).parameters
        assert "defer_upload" in params, f"{name} cannot defer"


def _logger():
    noop = lambda *a, **k: None  # noqa: E731
    return types.SimpleNamespace(
        debug=noop, info=noop, warning=noop, error=noop, exception=noop
    )


def _persist(monkeypatch, tmp_path, *, upload_raises=None):
    """Route one local folder and one Drive folder, stubbing the rest.

    A local copy is required: deferral is gated on it, because the inline path
    stages a temp file and deletes it in `finally`, so a background task would
    find nothing to upload. Returns (notifications, full_config, db).
    """
    notes = []
    monkeypatch.setattr(maker, "_drive_targets", lambda cfg, image_type: ["folder-A"])
    monkeypatch.setattr(maker, "_local_targets", lambda cfg, image_type: [str(tmp_path)])

    def fake_upload(path, folder, cfg, logger):
        if upload_raises:
            raise RuntimeError(upload_raises)

    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.upload_file", fake_upload, raising=False
    )
    monkeypatch.setattr(
        maker, "cl2k_generated_for", lambda db: types.SimpleNamespace(
            mark_uploaded=lambda *a, **k: None, record=lambda *a, **k: None
        )
    )

    cfg = types.SimpleNamespace(
        local_folders=[], gdrive_uploads=[], style="CL2K", priority=0
    )
    full = types.SimpleNamespace(cl2k_maker=cfg, sync_gdrive=object())
    monkeypatch.setattr("backend.util.config.load_config", lambda: full, raising=False)

    class FakeNotifier:
        def __init__(self, *a, **k):
            pass

        def send_notification(self, output, event="success"):
            notes.append((event, output))
            return {}

    monkeypatch.setattr(
        "backend.util.notification.NotificationManager", FakeNotifier, raising=False
    )
    db = types.SimpleNamespace(
        poster=types.SimpleNamespace(bulk_upsert=lambda rows: None)
    )
    return notes, full, db


def _run(maker_mod, db, full, logger, captured, **kw):
    return maker_mod._persist_poster(
        db=db,
        cfg=full.cl2k_maker,
        logger=logger,
        sync_cfg=object(),
        blob=b"x",
        kind="movie",
        title="T",
        year=2020,
        tmdb_id=1,
        tvdb_id=None,
        imdb_id=None,
        season_number=None,
        backdrop_path=None,
        logo_source="",
        save_local=True,
        upload_gdrive=True,
        image_type="logo",
        defer_upload=captured.append,
        full_config=full,
        **kw,
    )


def test_a_deferred_upload_failure_notifies(monkeypatch, tmp_path):
    """The caller already got "queued", so a failure has to reach the user some
    other way or it is lost entirely."""
    notes, full, db = _persist(monkeypatch, tmp_path, upload_raises="drive is down")
    errors = []
    logger = _logger()
    logger.error = errors.append

    captured = []
    result = _run(maker, db, full, logger, captured)
    assert result.get("upload_pending") is True
    assert not notes, "nothing should be reported before the deferred task runs"
    assert captured, "the upload should have been deferred"

    captured[0]()  # BackgroundTasks would call this after the response
    assert any(e == "failure" for e, _ in notes), "a failed deferred upload must notify"
    assert any("FAILED" in m for m in errors), "and must log at error level"


def test_a_deferred_success_does_not_notify(monkeypatch, tmp_path):
    notes, full, db = _persist(monkeypatch, tmp_path)
    captured = []
    _run(maker, db, full, _logger(), captured)
    captured[0]()
    assert not notes, "a clean upload must stay quiet"


def test_a_failed_config_reload_is_reported_not_swallowed(monkeypatch, tmp_path):
    """The deferred task re-reads config for live routing. If that read fails it
    used to log a warning and return — above the failure report — so the caller
    kept its "queued" success and heard nothing. .coderabbit.yaml names
    config-load explicitly: such a guard must never pass through silently."""
    notes, full, db = _persist(monkeypatch, tmp_path)
    errors = []
    logger = _logger()
    logger.error = errors.append

    captured = []
    _run(maker, db, full, logger, captured)
    assert captured, "the upload should have been deferred"

    # Config becomes unreadable between the response and the background task.
    def boom():
        raise RuntimeError("config.yml is empty")

    monkeypatch.setattr("backend.util.config.load_config", boom, raising=False)
    captured[0]()

    assert any(e == "failure" for e, _ in notes), "a failed reload must notify"
    assert any("FAILED" in m for m in errors), "and must log at error level"
    assert any("could not re-read config" in str(o) for _, o in notes), \
        "the notice must say what actually failed"


def test_losing_the_route_before_the_task_runs_is_reported(monkeypatch, tmp_path):
    """Third instance of the same class, found by sweeping rather than by review:
    if routing changes between the response and the background task, nothing
    uploads. It was an INFO log while the toast said "uploading to Drive"."""
    notes, full, db = _persist(monkeypatch, tmp_path)
    errors = []
    logger = _logger()
    logger.error = errors.append

    captured = []
    _run(maker, db, full, logger, captured)
    monkeypatch.setattr(maker, "_drive_targets", lambda cfg, image_type: [])
    captured[0]()

    assert any(e == "failure" for e, _ in notes), "losing the route must be reported"
    assert any("no Drive folder is routed" in str(o) for _, o in notes)

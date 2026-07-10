"""Tests for backend/util/job_processor.py — the process_job dispatch engine.

Covers the routing safety net: an unknown job type returns a structured error
(not a crash), and any handler exception is wrapped as JOB_EXCEPTION rather
than propagating out of the worker.
"""

from types import SimpleNamespace

import backend.util.job_processor as jp


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def test_unknown_job_type_returns_structured_error():
    res = jp.process_job({"id": 1, "type": "bogus", "payload": "{}"}, _logger())
    assert res["success"] is False
    assert res["error_code"] == "UNKNOWN_JOB_TYPE"


def test_handler_exception_is_wrapped(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    # Any dispatch handler raising must be caught and reported, never
    # propagated out of process_job (which would wedge the worker).
    monkeypatch.setattr(jp, "_process_cache_refresh_job", boom)
    res = jp.process_job({"id": 2, "type": "cache_refresh", "payload": "{}"}, _logger())
    assert res["success"] is False
    assert res["error_code"] == "JOB_EXCEPTION"
    assert "kaboom" in res["message"]


def test_dispatch_routes_to_matching_handler(monkeypatch):
    seen = {}

    def fake_cache_refresh(payload, logger, job_id, db):
        seen["payload"] = payload
        seen["job_id"] = job_id
        return {"success": True, "message": "ok"}

    monkeypatch.setattr(jp, "_process_cache_refresh_job", fake_cache_refresh)
    res = jp.process_job(
        {"id": 7, "type": "cache_refresh", "payload": '{"k": "v"}'}, _logger()
    )
    assert res["success"] is True
    assert seen["payload"] == {"k": "v"}
    assert seen["job_id"] == 7


# --- _process_media_record: per-season has_content + monitored override ---
# Regression: the webhook path copied the show dict for each season and only set
# season_number, so an unaired season inherited the show-level has_content
# (any-season-has-files) and lost its own monitored flag — clobbering a correct
# full sync on every webhook. Mirrors connector._process_arr_media.


def _normalized_show():
    """Shape produced by normalize_arr_media(arr_type='sonarr'): show-level
    has_content is the any-season rollup; each season carries its own
    season_has_episodes (episodeFileCount) and monitored."""
    return {
        "title": "Heated Rivalry",
        "year": 2025,
        "monitored": True,
        "has_content": True,  # rollup: S1 has files
        "seasons": [
            {"season_number": 1, "monitored": True, "season_has_episodes": 6},
            {"season_number": 2, "monitored": False, "season_has_episodes": 0},
        ],
    }


def test_process_media_record_season_has_content_overrides_show():
    rows = jp._process_media_record(_normalized_show(), "show")
    by_season = {r["season_number"]: r for r in rows}
    # Show row keeps the rollup.
    assert by_season[None]["has_content"] is True
    # S1 has files; S2 (unaired, 0 files) must NOT inherit the show's True.
    assert by_season[1]["has_content"] is True
    assert by_season[2]["has_content"] is False


def test_process_media_record_season_monitored_overrides_show():
    rows = jp._process_media_record(_normalized_show(), "show")
    by_season = {r["season_number"]: r for r in rows}
    # S2 is unmonitored at the season level — must not inherit show monitored=True.
    assert by_season[2]["monitored"] is False
    assert by_season[1]["monitored"] is True


def test_process_media_record_season_without_monitored_key_keeps_show():
    show = _normalized_show()
    show["seasons"] = [{"season_number": 1, "season_has_episodes": 5}]  # no monitored
    rows = jp._process_media_record(show, "show")
    s1 = next(r for r in rows if r["season_number"] == 1)
    assert s1["monitored"] is True  # falls back to the show's flag, not False


def test_process_media_record_movie_passthrough():
    movie = {"title": "The Matrix", "year": 1999, "has_content": True}
    rows = jp._process_media_record(movie, "movie")
    assert rows == [movie]


# --- media_sync job: sequential arr + gentle Plex + collections + mappings ---


def _media_sync_conn(calls):
    import types

    class _Conn:
        def __init__(self, *a, **k):
            self.connection_manager = types.SimpleNamespace(
                close_all_connections=lambda: calls.append("close")
            )

        def update_arr_database(self):
            calls.append("arr")
            return [
                types.SimpleNamespace(success=True),
                types.SimpleNamespace(success=False),
            ]

        def update_plex_database(self):  # the FORCED full walk — must NOT be used
            calls.append("plex_FORCED")
            return []

        def update_collections_database(self):
            calls.append("coll")
            return []

        def update_media_plex_mappings(self):
            calls.append("map")
            return {}

    return _Conn


def _cfg_with_plex(plex):
    import types

    return types.SimpleNamespace(instances=types.SimpleNamespace(plex=plex))


def test_media_sync_uses_gentle_plex_refresh_not_forced_walk(monkeypatch):
    import types

    calls = []
    refresh_args = []
    monkeypatch.setattr("backend.util.connector.Connector", _media_sync_conn(calls))
    monkeypatch.setattr("backend.util.connector.build_instance_map", lambda cfg: {})
    monkeypatch.setattr(
        "backend.util.plex_refresh.refresh_plex_cache_if_stale",
        lambda db, cfg, logger, enabled, **k: refresh_args.append(enabled) or True,
    )
    cfg = _cfg_with_plex({"Chodeus": types.SimpleNamespace(enabled=True)})
    monkeypatch.setattr("backend.util.config.load_config", lambda *a, **k: cfg)

    res = jp._process_media_sync_job({}, _logger(), 1, db=object())

    assert res["success"] is True
    assert "arr" in calls and "coll" in calls and "map" in calls
    assert "plex_FORCED" not in calls, (
        "must use the TTL-guarded refresh, not the forced walk"
    )
    assert refresh_args == [{"Chodeus": []}], (
        "gentle Plex refresh called for the enabled instance"
    )
    assert calls[-1] == "close"
    assert res["data"]["synced"] == 1 and res["data"]["attempted"] == 2


def test_media_sync_skips_plex_refresh_when_none_configured(monkeypatch):
    calls = []
    refresh_args = []
    monkeypatch.setattr("backend.util.connector.Connector", _media_sync_conn(calls))
    monkeypatch.setattr("backend.util.connector.build_instance_map", lambda cfg: {})
    monkeypatch.setattr(
        "backend.util.plex_refresh.refresh_plex_cache_if_stale",
        lambda db, cfg, logger, enabled, **k: refresh_args.append(enabled) or True,
    )
    monkeypatch.setattr(
        "backend.util.config.load_config", lambda *a, **k: _cfg_with_plex({})
    )

    res = jp._process_media_sync_job({}, _logger(), 1, db=object())

    assert res["success"] is True
    assert "arr" in calls
    assert refresh_args == [], "no Plex instances -> no refresh call"


# --- plex-path upload failure: surfaced instead of swallowed ---
# _handle_post_rename_actions used to discard PosterUploader.run()'s result, so
# a failed synchronous webhook upload never failed anything and no retry ran.


def test_poster_rename_job_fails_when_upload_fails(monkeypatch):
    """A poster_rename job whose rename succeeded but whose upload failed must
    fail (UPLOAD_FAILED) so the worker's backoff retry re-stages + re-uploads."""
    monkeypatch.setattr(
        "backend.modules.poster_renamerr.PosterRenamerr", lambda logger: object()
    )
    monkeypatch.setattr(
        jp,
        "_adhoc_rename_and_post",
        lambda *a, **k: {
            "success": True,
            "output": {"x": 1},
            "upload_result": {"success": False, "message": "boom"},
        },
    )

    res = jp._process_poster_rename_job({"media_items": [{}]}, _logger(), 1)
    assert res["success"] is False
    assert res["error_code"] == "UPLOAD_FAILED"
    assert "boom" in res["message"]


def test_adhoc_rename_attaches_upload_result(monkeypatch):
    """The synchronous plex-path upload result rides along on the rename result
    (rename success is NOT flipped — each caller decides what a failed upload
    means for its job)."""
    from contextlib import contextmanager
    from types import SimpleNamespace as NS

    @contextmanager
    def _staging():
        yield None

    renamer = NS(
        apply_staging=_staging,
        run_poster_rename_adhoc=lambda items: {
            "success": True,
            "output": {"movie": [{"title": "Dune"}]},
            "manifest": {"media_cache": [1]},
        },
        config=NS(apply_method="plex", run_border_replacerr=False),
        full_config=None,
    )

    class _StubNotifier:
        def __init__(self, *a, **k):
            pass

        def send_notification(self, *a, **k):
            pass

    class _StubDB:
        def __init__(self, *a, **k):
            self.plex = NS(count=lambda: 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _StubUploader:
        def __init__(self, *a, **k):
            pass

        def run(self):
            return {"success": False, "message": "boom"}

    monkeypatch.setattr("backend.util.notification.NotificationManager", _StubNotifier)
    monkeypatch.setattr(jp, "_check_plex_upload_enabled", lambda cfg: True)
    monkeypatch.setattr(jp, "ChubDB", _StubDB)
    monkeypatch.setattr("backend.util.upload_posters.PosterUploader", _StubUploader)

    result = jp._adhoc_rename_and_post(renamer, [{}], _logger(), 1)
    assert result["success"] is True
    assert result["upload_result"]["success"] is False

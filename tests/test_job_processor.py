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

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

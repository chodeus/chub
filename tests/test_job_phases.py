"""Tests for per-phase job timing (worker phase methods + ChubModule._phase)."""

import json
from types import SimpleNamespace

import pytest

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from tests.conftest import StubLogger


def _open_db(tmp_path):
    db = ChubDB(logger=StubLogger(), db_path=str(tmp_path / "jobs.db"), quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    return db


def _new_job(db):
    return db.worker.execute_query(
        "INSERT INTO jobs (type, status) VALUES ('module_run', 'running')",
        last_row_id=True,
    )


def _phases(db, jid):
    row = db.worker.execute_query(
        "SELECT phases FROM jobs WHERE id=?", (jid,), fetch_one=True
    )
    return json.loads(row["phases"]) if row and row["phases"] else []


def test_declare_start_finish_phase(tmp_path):
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        db.worker.declare_phases("jobs", jid, ["sync", "merge", "match"])
        ph = _phases(db, jid)
        assert [p["name"] for p in ph] == ["sync", "merge", "match"]
        assert all(p["status"] == "pending" for p in ph)

        db.worker.start_phase("jobs", jid, "sync")
        sync = next(p for p in _phases(db, jid) if p["name"] == "sync")
        assert sync["status"] == "running"
        assert sync["started_at"] is not None

        db.worker.finish_phase("jobs", jid, "sync")
        sync = next(p for p in _phases(db, jid) if p["name"] == "sync")
        assert sync["status"] == "success"
        assert sync["finished_at"] is not None
        assert isinstance(sync["duration_s"], (int, float))
        # untouched phases stay pending
        assert next(p for p in _phases(db, jid) if p["name"] == "merge")[
            "status"
        ] == "pending"
    finally:
        db.__exit__(None, None, None)


def test_finish_phase_error_and_undeclared_append(tmp_path):
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        # Undeclared phase: start_phase appends it.
        db.worker.start_phase("jobs", jid, "border")
        db.worker.finish_phase("jobs", jid, "border", status="error", error="boom")
        border = next(p for p in _phases(db, jid) if p["name"] == "border")
        assert border["status"] == "error"
        assert border["error"] == "boom"

        # finish on a non-running phase is a no-op (doesn't raise).
        db.worker.finish_phase("jobs", jid, "nope")
    finally:
        db.__exit__(None, None, None)


def test_skip_pending_phases(tmp_path):
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        db.worker.declare_phases("jobs", jid, ["a", "b", "c"])
        db.worker.start_phase("jobs", jid, "a")
        db.worker.finish_phase("jobs", jid, "a")
        db.worker.skip_pending_phases("jobs", jid)
        statuses = {p["name"]: p["status"] for p in _phases(db, jid)}
        assert statuses == {"a": "success", "b": "skipped", "c": "skipped"}
    finally:
        db.__exit__(None, None, None)


def test_phase_context_manager_records_and_propagates(tmp_path):
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        fake = SimpleNamespace(_job_id=jid, _job_db=db)

        with ChubModule._phase(fake, "compose"):
            pass
        compose = next(p for p in _phases(db, jid) if p["name"] == "compose")
        assert compose["status"] == "success"

        # An exception inside the phase marks it error AND propagates.
        with pytest.raises(ValueError):
            with ChubModule._phase(fake, "boom"):
                raise ValueError("kaboom")
        boom = next(p for p in _phases(db, jid) if p["name"] == "boom")
        assert boom["status"] == "error"
        assert "kaboom" in boom["error"]
    finally:
        db.__exit__(None, None, None)


def test_phase_context_manager_noop_without_job_context(tmp_path):
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        # No job id -> no writes, no crash (CLI / nested sub-module case).
        fake = SimpleNamespace(_job_id=None, _job_db=db)
        with ChubModule._phase(fake, "x"):
            pass
        assert _phases(db, jid) == []
    finally:
        db.__exit__(None, None, None)


def test_progress_and_phases_dont_clobber(tmp_path):
    """update_progress and phase writes hit the same job row but different
    columns — neither may overwrite the other (guards against a future
    SELECT *-then-UPDATE-all refactor)."""
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        db.worker.declare_phases("jobs", jid, ["a", "b"])
        db.worker.start_phase("jobs", jid, "a")
        db.worker.update_progress("jobs", jid, 25)
        db.worker.finish_phase("jobs", jid, "a")
        db.worker.update_progress("jobs", jid, 50)
        db.worker.start_phase("jobs", jid, "b")

        row = db.worker.execute_query(
            "SELECT progress, phases FROM jobs WHERE id=?", (jid,), fetch_one=True
        )
        assert row["progress"] == 50
        statuses = {p["name"]: p["status"] for p in json.loads(row["phases"])}
        assert statuses == {"a": "success", "b": "running"}
    finally:
        db.__exit__(None, None, None)


def test_phase_error_swallowed_by_caller_marks_error_and_continues(tmp_path):
    """The asset_renamerr idiom: try/except OUTSIDE the phase so a failure marks
    the phase 'error' (accurate timeline) while the run continues (non-fatal)."""
    db = _open_db(tmp_path)
    try:
        jid = _new_job(db)
        fake = SimpleNamespace(_job_id=jid, _job_db=db)
        continued = False
        try:
            with ChubModule._phase(fake, "sync_gdrive"):
                raise RuntimeError("sync blew up")
        except Exception:
            pass  # caller swallows -> sync is non-fatal
        continued = True
        sync = next(p for p in _phases(db, jid) if p["name"] == "sync_gdrive")
        assert sync["status"] == "error"
        assert continued
    finally:
        db.__exit__(None, None, None)

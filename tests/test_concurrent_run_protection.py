"""Regression tests for the three concurrent-run protections.

1. Logger.start_time resets on every instantiation (logger.py fix).
2. DBWorker.enqueue_job dedupes module_run by module_name (worker.py fix).
3. _process_module_run_job acquires a per-module advisory lock and
   returns deferred=True when the lock is already held (job_processor.py).
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.database import ChubDB
from backend.util.logger import Logger


class _StubLogger:
    def __getattr__(self, _name):
        return lambda *a, **kw: None

    def get_adapter(self, *a, **kw):
        return self


def test_logger_start_time_resets_on_reinit(tmp_path, monkeypatch):
    """Second Logger() in the same process must reset start_time.

    Without the fix, the _initialized cache would short-circuit
    __init__ and leave the original start_time stamped at first-init
    time, causing log_outro() to report cumulative process uptime
    instead of this run's duration.
    """
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    Logger._initialized.clear()

    first = Logger(log_level="INFO", module_name="test_logger_reset_a")
    first_start = first.start_time
    assert isinstance(first_start, datetime)

    time.sleep(0.02)

    second = Logger(log_level="INFO", module_name="test_logger_reset_a")
    second_start = second.start_time

    assert second_start > first_start, (
        f"second start_time {second_start} should be after first {first_start}"
    )
    # _logger.start_time mirror is also reset (log_outro reads it from
    # the underlying logging.Logger via the adapter path).
    assert second._logger.start_time == second_start


def test_enqueue_module_run_dedupes_by_module_name(tmp_path):
    """Two module_run enqueues for the same module collapse to one job."""
    db = ChubDB(logger=_StubLogger(), db_path=str(tmp_path / "t.db"), quiet=True)
    db.__enter__()
    try:
        first = db.worker.enqueue_job(
            table_name="jobs",
            payload={"module_name": "poster_renamerr", "origin": "test"},
            job_type="module_run",
        )
        assert first["success"] is True
        assert not first.get("deduped")
        first_id = first["data"]["job_id"]

        second = db.worker.enqueue_job(
            table_name="jobs",
            payload={"module_name": "poster_renamerr", "origin": "test"},
            job_type="module_run",
        )
        assert second["success"] is True
        assert second.get("deduped") is True, second
        assert second["data"]["job_id"] == first_id

        # Different module_name -> separate job.
        other = db.worker.enqueue_job(
            table_name="jobs",
            payload={"module_name": "sync_gdrive", "origin": "test"},
            job_type="module_run",
        )
        assert other["success"] is True
        assert not other.get("deduped")
        assert other["data"]["job_id"] != first_id
    finally:
        db.__exit__(None, None, None)


def test_enqueue_non_module_run_jobs_do_not_dedupe(tmp_path):
    """Dedupe must be scoped to module_run; other job types still fan out."""
    db = ChubDB(logger=_StubLogger(), db_path=str(tmp_path / "t.db"), quiet=True)
    db.__enter__()
    try:
        a = db.worker.enqueue_job(
            table_name="jobs",
            payload={"manifest": {}},
            job_type="upload_posters",
        )
        b = db.worker.enqueue_job(
            table_name="jobs",
            payload={"manifest": {}},
            job_type="upload_posters",
        )
        assert a["data"]["job_id"] != b["data"]["job_id"]
        assert not a.get("deduped")
        assert not b.get("deduped")
    finally:
        db.__exit__(None, None, None)


def test_enqueue_dedupe_excludes_completed_jobs(tmp_path):
    """A finished module_run shouldn't block a fresh enqueue."""
    db = ChubDB(logger=_StubLogger(), db_path=str(tmp_path / "t.db"), quiet=True)
    db.__enter__()
    try:
        first = db.worker.enqueue_job(
            table_name="jobs",
            payload={"module_name": "poster_renamerr", "origin": "test"},
            job_type="module_run",
        )
        first_id = first["data"]["job_id"]

        # Mark the first job as completed.
        with db.worker.get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'success' WHERE id = ?",
                (first_id,),
            )
            conn.commit()

        second = db.worker.enqueue_job(
            table_name="jobs",
            payload={"module_name": "poster_renamerr", "origin": "test"},
            job_type="module_run",
        )
        assert not second.get("deduped")
        assert second["data"]["job_id"] != first_id
    finally:
        db.__exit__(None, None, None)


def test_process_module_run_returns_deferred_when_lock_held():
    """If the per-module advisory lock is already held, the handler
    returns success+deferred without invoking the module."""
    from backend.util.job_processor import (
        _get_module_lock,
        _process_module_run_job,
    )

    module_name = "test_lock_blocking_module_xyz"
    lock = _get_module_lock(module_name)
    assert lock.acquire(blocking=False)
    try:
        result = _process_module_run_job(
            payload={"module_name": module_name, "origin": "test"},
            logger=_StubLogger(),
            job_id=12345,
        )
        assert result["success"] is True
        assert result.get("deferred") is True
        assert result["data"]["module"] == module_name
    finally:
        lock.release()


def test_get_module_lock_is_idempotent_per_module():
    from backend.util.job_processor import _get_module_lock

    a1 = _get_module_lock("module_a")
    a2 = _get_module_lock("module_a")
    b = _get_module_lock("module_b")

    assert a1 is a2
    assert a1 is not b

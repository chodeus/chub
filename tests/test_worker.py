"""Tests for backend/util/database/worker.py — the job-queue engine: atomic
claim, webhook/general partition, retry-vs-permanent-fail, and cleanup."""

from types import SimpleNamespace

import pytest

from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _enqueue(db, job_type, payload=None):
    res = db.worker.enqueue_job("jobs", payload or {}, job_type=job_type)
    return res["data"]["job_id"]


def _running(db, jid, attempts):
    db.worker.execute_query(
        "UPDATE jobs SET status='running', attempts=? WHERE id=?", (attempts, jid)
    )


def _raise(exc):
    raise exc


@pytest.mark.parametrize(
    "prior_attempts, outcome",
    [
        (0, lambda: {"success": True}),
        (0, lambda: {"success": False, "message": "Cache refresh failed"}),
        (2, lambda: {"success": False, "message": "Cache refresh failed"}),
        (0, lambda: _raise(RuntimeError("boom"))),
    ],
    ids=["success", "failure-with-retries-left", "final-failure", "exception"],
)
def test_a_job_cancelled_while_it_runs_stays_cancelled(db, prior_attempts, outcome):
    jid = _enqueue(db, "cache_refresh")
    db.worker.execute_query("UPDATE jobs SET attempts=? WHERE id=?", (prior_attempts, jid))

    def process(job, _log):
        # What DELETE /modules/{name}/execution/{id} does while the module runs.
        assert db.worker.cancel_running_job(job["id"], "2026-11-10T00:00:00+00:00") == 1
        db.worker.running = False
        return outcome()

    db.worker.running = True
    db.worker.process_pending_jobs("jobs", process)

    row = db.worker.get_job_by_id("jobs", jid)
    assert (row["status"], row["error"], row["scheduled_at"], row["completed_at"]) == (
        "cancelled", None, None, "2026-11-10T00:00:00+00:00"
    )
    assert (db.worker._jobs_processed, db.worker._jobs_failed) == (0, 0)
    assert db.worker.claim_next_job("jobs") is None


def test_claim_stamps_running_and_increments_attempts(db):
    jid = _enqueue(db, "cache_refresh")
    claimed = db.worker.claim_next_job("jobs")
    assert claimed is not None and claimed["id"] == jid
    row = db.worker.execute_query(
        "SELECT status, attempts FROM jobs WHERE id=?", (jid,), fetch_one=True
    )
    assert row["status"] == "running"
    assert row["attempts"] == 1
    # The claim UPDATE is guarded by `AND status='pending'`, so a second claim
    # finds nothing — two workers can't grab the same job.
    assert db.worker.claim_next_job("jobs") is None


def test_general_worker_excludes_webhook_jobs(db):
    _enqueue(db, "webhook")
    _enqueue(db, "cache_refresh")
    # The general worker (no filter) must skip webhook jobs.
    claimed = db.worker.claim_next_job("jobs")
    assert claimed is not None and claimed["type"] == "cache_refresh"
    # The webhook job is only claimable by the webhook-filtered worker.
    wh = db.worker.claim_next_job("jobs", job_type_filter="webhook")
    assert wh is not None and wh["type"] == "webhook"


def test_handle_job_error_retries_then_fails_permanently(db):
    jid = _enqueue(db, "cache_refresh")
    # Below max_attempts (default 3): retry — back to pending with a backoff.
    _running(db, jid, attempts=1)
    db.worker._handle_job_error("jobs", jid, RuntimeError("boom"), 0.1, _logger())
    row = db.worker.execute_query(
        "SELECT status, scheduled_at FROM jobs WHERE id=?", (jid,), fetch_one=True
    )
    assert row["status"] == "pending"
    assert row["scheduled_at"] is not None
    # At the ceiling: permanent error.
    _running(db, jid, attempts=3)
    db.worker._handle_job_error("jobs", jid, RuntimeError("boom"), 0.1, _logger())
    row = db.worker.execute_query(
        "SELECT status FROM jobs WHERE id=?", (jid,), fetch_one=True
    )
    assert row["status"] == "error"


def test_a_stored_job_error_never_holds_exception_text(db):
    """The jobs table's error reaches the browser through the job APIs."""
    from backend.util.database.worker import JobFailed

    jid = _enqueue(db, "cache_refresh")
    _running(db, jid, attempts=3)
    db.worker._handle_job_error(
        "jobs", jid, RuntimeError("/srv token=hunter2"), 0.1, _logger()
    )
    row = db.worker.execute_query("SELECT error FROM jobs WHERE id=?", (jid,), fetch_one=True)
    assert row["error"] == "Job failed: unexpected error — see the server log"

    # A job's own failure message is already worded for the browser: kept as is.
    jid2 = _enqueue(db, "cache_refresh")
    _running(db, jid2, attempts=3)
    failed = JobFailed("Job failed: Cache refresh failed: timed out")
    db.worker._handle_job_error("jobs", jid2, failed, 0.1, _logger())
    row = db.worker.execute_query("SELECT error FROM jobs WHERE id=?", (jid2,), fetch_one=True)
    assert row["error"] == "Job failed: Cache refresh failed: timed out"


def test_cleanup_deletes_only_old_finished_jobs(db):
    old = "2000-01-01T00:00:00+00:00"
    for status in ("success", "error", "pending"):
        db.worker.execute_query(
            "INSERT INTO jobs (type, received_at, status) VALUES (?,?,?)",
            ("t", old, status),
        )
    _enqueue(db, "recent")  # received_at = now, status pending

    res = db.worker.cleanup_jobs("jobs", days=30)
    assert res["success"] is True
    assert res["data"]["deleted"] == 2  # old success + old error only

    remaining = db.worker.execute_query("SELECT status FROM jobs", fetch_all=True)
    assert sorted(r["status"] for r in remaining) == ["pending", "pending"]


def test_retry_wins_once_and_reports_invalid_state_on_the_second(db):
    """Two retries of the same errored job: one resets it, the other is refused."""
    jid = _enqueue(db, "module_run")
    db.worker.execute_query("UPDATE jobs SET status='error' WHERE id=?", (jid,))

    assert db.worker.reset_job_to_pending("jobs", jid) is True
    assert db.worker.reset_job_to_pending("jobs", jid) is False


def test_retry_does_not_resurrect_a_job_claimed_mid_transaction(db, monkeypatch):
    """A retry that loses the race must not reset a job a worker already claimed."""
    jid = _enqueue(db, "module_run")
    db.worker.execute_query("UPDATE jobs SET status='error' WHERE id=?", (jid,))

    real = db.worker.execute_query

    def racing(query, *args, **kwargs):
        result = real(query, *args, **kwargs)
        if query.lstrip().upper().startswith("SELECT * FROM JOBS"):
            # Between our status check and our UPDATE, another retry lands and a
            # worker claims the row — exactly what concurrent handlers can do.
            real("UPDATE jobs SET status='running', attempts=1 WHERE id=?", (jid,))
        return result

    monkeypatch.setattr(db.worker, "execute_query", racing)
    assert db.worker.reset_job_to_pending("jobs", jid) is False
    monkeypatch.undo()

    row = db.worker.execute_query(
        "SELECT status, attempts FROM jobs WHERE id=?", (jid,), fetch_one=True
    )
    assert row["status"] == "running", "a running job was reset out from under a worker"
    assert row["attempts"] == 1

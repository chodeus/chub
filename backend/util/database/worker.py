# util/database/worker.py
import datetime
import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .db_base import DatabaseBase


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class JobResult:
    status: int
    success: bool
    message: str
    error_code: Optional[str] = None
    data: Optional[Dict] = None


class DBWorker(DatabaseBase):
    """
    Simplified DB-backed job worker that delegates processing to job_processor.py

    SQL identity: every public method takes a `table_name` which is
    interpolated into SQL as an f-string. Callers are internal code only,
    but we guard with an allowlist so a future refactor that accidentally
    routes user input into `table_name` can't open a SQL-injection hole.
    """

    _POLL_TIMEOUT = 1  # max seconds to wait between job polls

    # Allowlist of table names this worker is permitted to read/write.
    # Only "jobs" exists today; new tables require an explicit entry.
    _ALLOWED_TABLES = frozenset({"jobs"})

    # Class-level event shared by ALL DBWorker instances.
    # enqueue_job() may be called on the DEFAULT worker (db.worker) while
    # the actual processing threads run on separate WEBHOOK/BACKGROUND
    # instances.  A class-level event ensures the signal reaches every
    # waiting worker regardless of which instance enqueued the job.
    _job_event = threading.Event()

    @classmethod
    def _check_table(cls, name: str) -> str:
        if name not in cls._ALLOWED_TABLES:
            raise ValueError(
                f"Refusing to operate on table {name!r}: "
                f"not in allowlist {sorted(cls._ALLOWED_TABLES)}"
            )
        return name

    def __init__(
        self,
        db_path,
        logger,
        num_workers: int = 3,
        worker_name: str = "UNNAMED",
        job_type_filter: str = None,
        cleanup_interval: int = 3600,
        job_deletion_days: int = 30,
        max_retry_delay: int = 300,
    ):
        super().__init__(logger, db_path)
        # self.logger is set by super().__init__
        self.worker_name = worker_name
        self.job_type_filter = job_type_filter
        self.running = False
        self.max_retry_delay = max_retry_delay

        # Threading
        self._threads = []
        self._cleanup_thread = None
        self._cleanup_running = False
        self.num_workers = num_workers

        # Cleanup settings
        self.cleanup_interval = cleanup_interval
        self.job_deletion_days = job_deletion_days

        # Basic stats
        self._jobs_processed = 0
        self._jobs_failed = 0

        # Shutdown handling
        self._shutdown_event = threading.Event()
        self._shutdown_requested = False

        # Simple signal handling
        if threading.current_thread() is threading.main_thread():
            # Signal handling is managed by the main application (main.py)
            # Workers respond to shutdown via the shutdown_event, not direct signal handling
            pass

    def _calculate_retry_delay(self, attempt: int) -> int:
        """Simple exponential backoff"""
        return min(2**attempt, self.max_retry_delay)

    def process_pending_jobs(self, table_name: str, process_fn: Callable):
        """Main job processing loop"""
        self._check_table(table_name)
        log = self.logger.get_adapter(f"WORKER:{self.worker_name}")

        while self.running and not self._shutdown_event.is_set():
            try:
                if self._shutdown_requested:
                    log.info("Shutdown requested, stopping job processing...")
                    break

                # Clear before claiming so any signal that arrives during or
                # after the DB query is preserved for the subsequent wait().
                self._job_event.clear()
                job = self.claim_next_job(table_name, self.job_type_filter)
                if not job:
                    timeout = 0.5 if self._shutdown_requested else self._POLL_TIMEOUT
                    self._job_event.wait(timeout=timeout)
                    continue

                job_id = job["id"]
                job_type = job.get("type", "unknown")

                log.debug(f"Processing {table_name} job ID {job_id} (type={job_type})")

                start_time = time.time()
                try:
                    result = process_fn(job, self.logger)
                    duration = time.time() - start_time

                    # Handle different result types
                    if isinstance(result, JobResult):
                        if result.success:
                            self.mark_job_complete(table_name, job_id, result.__dict__)
                            self._jobs_processed += 1
                            log.debug(
                                f"Job {job_id} completed successfully in {duration:.2f}s"
                            )
                        else:
                            raise Exception(f"Job failed: {result.message}")
                    elif isinstance(result, dict) and result.get("success"):
                        self.mark_job_complete(table_name, job_id, result)
                        self._jobs_processed += 1
                        log.debug(
                            f"Job {job_id} completed successfully in {duration:.2f}s"
                        )
                    else:
                        raise Exception(
                            f"Job failed: {result.get('message', 'Unknown error') if isinstance(result, dict) else str(result)}"
                        )

                except Exception as ex:
                    duration = time.time() - start_time
                    self._handle_job_error(table_name, job_id, ex, duration, log)

            except Exception as ex:
                log.error(f"Loop error: {ex}", exc_info=True)
                # Intentionally wait on _shutdown_event (not _job_event) so we
                # back off after errors instead of immediately retrying.
                timeout = 0.5 if self._shutdown_requested else self._POLL_TIMEOUT
                self._shutdown_event.wait(timeout=timeout)

        log.info(f"Worker {self.worker_name} finished processing jobs")

    def _handle_job_error(
        self, table_name: str, job_id: int, error: Exception, duration: float, log
    ):
        """Simple error handling with retry"""
        try:
            row = self.get_attempts(table_name, job_id)
            attempts = row["attempts"]
            max_attempts = row["max_attempts"]

            if attempts < max_attempts:
                delay = self._calculate_retry_delay(attempts)
                scheduled_at = (
                    datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(seconds=delay)
                ).isoformat()

                self.mark_job_pending_with_error(
                    table_name, job_id, error, scheduled_at
                )
                log.warning(
                    f"Job {job_id} failed (attempt {attempts}/{max_attempts}) in {duration:.2f}s: {error}. "
                    f"Will retry in {delay}s"
                )
            else:
                self.mark_job_failed(table_name, job_id, error)
                self._jobs_failed += 1
                log.error(
                    f"Job {job_id} failed permanently after {attempts} attempts in {duration:.2f}s: {error}",
                    exc_info=True,
                )
        except Exception as meta_error:
            log.error(
                f"Error handling job error for job {job_id}: {meta_error}",
                exc_info=True,
            )

    def get_pending_jobs(self, table_name: str, job_type_filter: str = None):
        query = f"""SELECT * FROM {table_name}
                    WHERE status='pending'
                    AND (attempts < max_attempts OR max_attempts IS NULL)
                    AND (scheduled_at IS NULL OR scheduled_at <= ?)
                """
        params = [datetime.datetime.now(datetime.timezone.utc).isoformat()]
        if job_type_filter:
            query += " AND type=?"
            params.append(job_type_filter)
        query += " ORDER BY received_at ASC"
        return self.execute_query(query, tuple(params), fetch_all=True)

    def mark_job_complete(self, table_name: str, job_id: int, result):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.execute_query(
            f"UPDATE {table_name} SET status='success', result=?, completed_at=? WHERE id=?",
            (json.dumps(result) if result else None, now, job_id),
        )

    def get_attempts(self, table_name: str, job_id: int):
        return self.execute_query(
            f"SELECT attempts, max_attempts FROM {table_name} WHERE id=?",
            (job_id,),
            fetch_one=True,
        )

    def mark_job_pending_with_error(
        self, table_name: str, job_id: int, error, scheduled_at: str = None
    ):
        if scheduled_at:
            self.execute_query(
                f"UPDATE {table_name} SET status='pending', error=?, scheduled_at=? WHERE id=?",
                (str(error), scheduled_at, job_id),
            )
        else:
            self.execute_query(
                f"UPDATE {table_name} SET status='pending', error=? WHERE id=?",
                (str(error), job_id),
            )

    def mark_job_failed(self, table_name: str, job_id: int, error):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.execute_query(
            f"UPDATE {table_name} SET status='error', error=?, completed_at=? WHERE id=?",
            (str(error), now, job_id),
        )

    def reset_job_to_pending(self, table_name: str, job_id: int):
        """Reset a job to 'pending' status"""
        self._check_table(table_name)
        row = self.execute_query(
            f"SELECT * FROM {table_name} WHERE id=?", (job_id,), fetch_one=True
        )
        if not row:
            return None
        if row["status"] not in ("error", "success"):
            return False
        self.execute_query(
            f"UPDATE {table_name} SET status='pending', attempts=0, scheduled_at=NULL, error=NULL, result=NULL, started_at=NULL, completed_at=NULL WHERE id=?",
            (job_id,),
        )
        return True

    def claim_next_job(self, table_name: str, job_type_filter: str = None):
        """Claim the next available job"""
        self._check_table(table_name)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        query = f"""SELECT * FROM {table_name}
                    WHERE status='pending'
                    AND (attempts < max_attempts OR max_attempts IS NULL)
                    AND (scheduled_at IS NULL OR scheduled_at <= ?)
                """
        params = [now]

        if job_type_filter is not None:
            # Restrict this worker to only claim jobs of the given type
            query += " AND type=?"
            params.append(job_type_filter)
        else:
            # General worker: exclude webhook jobs (handled by dedicated worker)
            query += " AND type!=?"
            params.append("webhook")

        query += " ORDER BY COALESCE(priority, 0) DESC, received_at ASC LIMIT 1"

        row = self.execute_query(query, tuple(params), fetch_one=True)
        if not row:
            return None

        job_id = row["id"]
        # Stamp started_at on claim; completed_at is reset so a retried row
        # doesn't inherit the previous attempt's finish time.
        updated = self.execute_query(
            f"UPDATE {table_name} SET status='running', attempts=attempts+1, started_at=?, completed_at=NULL WHERE id=? AND status='pending'",
            (now, job_id),
        )
        if updated == 1:
            return dict(row)
        else:
            return None

    def get_worker_stats(self):
        """Get basic worker stats"""
        return {
            "worker_name": self.worker_name,
            "status": "running" if self.running else "stopped",
            "jobs_processed": self._jobs_processed,
            "jobs_failed": self._jobs_failed,
            "active_threads": len([t for t in self._threads if t.is_alive()]),
            "num_workers": self.num_workers,
        }

    def _reset_stuck_jobs(self, table_name: str) -> int:
        """Revert THIS worker's stuck 'running' jobs to 'pending' on startup.

        Clears timing and gives back the attempt a hard-kill consumed. Scoped to
        this worker's job partition (mirrors claim_next_job) so a shared-table
        sibling never reverts a job the other worker already claimed.
        """
        sql = (
            f"UPDATE {table_name} SET status='pending', started_at=NULL, "
            f"completed_at=NULL, attempts=MAX(attempts - 1, 0) WHERE status='running'"
        )
        params = []
        if self.job_type_filter is not None:
            sql += " AND type=?"
            params.append(self.job_type_filter)
        else:
            sql += " AND type!=?"
            params.append("webhook")
        return self.execute_query(sql, tuple(params)) or 0

    def start(
        self,
        table_name: str = "jobs",
        process_fn: Callable = None,
        job_type_filter: str = None,
    ):
        """
        Start the worker - FIXED to use dedicated job processor by default
        """
        self._check_table(table_name)
        log = self.logger.get_adapter("WORKER")

        # FIXED: Use the dedicated job processor if no process_fn provided
        if process_fn is None:
            from backend.util.job_processor import process_job

            process_fn = process_job
            log.debug("Using dedicated job processor from backend.util.job_processor")

        if self._threads and all(t.is_alive() for t in self._threads):
            log.info("Already running.")
            return

        # Run AFTER the already-running guard so we never revert jobs this
        # worker is actively processing.
        reset = self._reset_stuck_jobs(table_name)
        if reset:
            log.info(f"Reset {reset} 'running' jobs to 'pending' on startup.")

        self.running = True
        self._shutdown_event.clear()
        self._shutdown_requested = False
        self._threads = []

        # Start worker threads
        for i in range(self.num_workers):
            t = threading.Thread(
                target=self.process_pending_jobs,
                args=(table_name, process_fn),
                daemon=True,
                name=f"{self.worker_name}-Worker-{i + 1}",
            )
            t.start()
            self._threads.append(t)

        # Start cleanup thread
        if not self._cleanup_thread or not self._cleanup_thread.is_alive():
            self._cleanup_running = True
            self._cleanup_thread = threading.Thread(
                target=self._periodic_cleanup,
                args=(table_name,),
                daemon=True,
                name=f"{self.worker_name}-Cleanup",
            )
            self._cleanup_thread.start()

        log.info(
            f"Starting '{self.num_workers}' worker(s) for '{job_type_filter if job_type_filter is not None else 'Any'}' jobs..."
        )
        log.debug(
            f"(poll_timeout={self._POLL_TIMEOUT}s, job_type_filter='{self.job_type_filter}', using dedicated job_processor)"
        )

    def stop(self, timeout: int = 10):
        """Stop the worker gracefully"""
        log = self.logger.get_adapter("WORKER")
        log.info(f"Initiating graceful shutdown of '{self.worker_name}'...")

        # Set shutdown flags
        self.running = False
        self._cleanup_running = False
        self._shutdown_event.set()
        self._shutdown_requested = True
        self._job_event.set()  # wake workers blocked on job wait

        # Stop worker threads
        alive_threads = [t for t in self._threads if t.is_alive()]

        if alive_threads:
            log.info(f"Waiting for {len(alive_threads)} worker threads to stop...")
            for thread in alive_threads:
                thread.join(timeout=2)

        # Stop cleanup thread
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)

        # Clear thread references
        self._threads.clear()
        self._cleanup_thread = None

        log.info("Worker stopped")

    def close(self):
        """Close the worker and database connection"""
        try:
            self.stop(timeout=5)
        except Exception as e:
            if hasattr(self, "logger") and self.logger:
                self.logger.get_adapter("WORKER").error(
                    f"Error during worker close: {e}", exc_info=True
                )

    def job_stats(self, table_name: str = "jobs", error_limit: int = 10):
        self._check_table(table_name)
        try:
            status_rows = self.execute_query(
                f"SELECT status, COUNT(*) AS count FROM {table_name} GROUP BY status",
                fetch_all=True,
            )
            status_counts = (
                {row["status"]: row["count"] for row in status_rows}
                if status_rows
                else {}
            )

            total_row = self.execute_query(
                f"SELECT COUNT(*) as total FROM {table_name}", fetch_one=True
            )
            total = total_row["total"] if total_row else 0

            error_rows = self.execute_query(
                f"SELECT id, type, received_at, error FROM {table_name} WHERE status='error' ORDER BY received_at DESC LIMIT ?",
                (error_limit,),
                fetch_all=True,
            )
            recent_errors = [dict(row) for row in error_rows] if error_rows else []

            last_row = self.execute_query(
                f"SELECT id, type, status, received_at FROM {table_name} ORDER BY received_at DESC LIMIT 1",
                fetch_one=True,
            )

            return {
                "success": True,
                "message": "Job stats fetched",
                "data": {
                    "total": total,
                    "status_counts": status_counts,
                    "recent_errors": recent_errors,
                    "last_job": dict(last_row) if last_row else None,
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error fetching job stats: {e}",
                "error_code": "DB_JOB_STATS_ERROR",
            }

    def count_by_status(self, status: str, table_name: str = "jobs") -> int:
        """Number of jobs currently in one status."""
        self._check_table(table_name)
        row = self.execute_query(
            f"SELECT COUNT(*) AS total FROM {table_name} WHERE status=?",  # noqa: S608
            (status,),
            fetch_one=True,
        )
        return int(row["total"]) if row else 0

    def count_by_status_since(
        self, cutoff: str, table_name: str = "jobs"
    ) -> Dict[str, int]:
        """{status: count} for jobs received at or after an ISO cutoff."""
        self._check_table(table_name)
        rows = self.execute_query(
            f"SELECT status, COUNT(*) AS total FROM {table_name} "  # noqa: S608
            "WHERE received_at >= ? GROUP BY status",
            (cutoff,),
            fetch_all=True,
        )
        return {row["status"]: row["total"] for row in rows or []}

    def recent_failures(
        self, cutoff: str, limit: int = 20, table_name: str = "jobs"
    ) -> List[Dict[str, Any]]:
        """Errored jobs since an ISO cutoff, newest first."""
        self._check_table(table_name)
        # `, id DESC` breaks ties: received_at has second-level collisions under
        # a webhook burst, so without it the LIMIT window would be arbitrary.
        rows = self.execute_query(
            f"SELECT id, type, payload, error, received_at FROM {table_name} "  # noqa: S608
            "WHERE status='error' AND received_at >= ? "
            "ORDER BY received_at DESC, id DESC LIMIT ?",
            (cutoff, limit),
            fetch_all=True,
        )
        return [dict(r) for r in rows or []]

    def jobs_of_type_since(
        self, job_type: str, cutoff: str, table_name: str = "jobs"
    ) -> List[Dict[str, Any]]:
        """Jobs of one type received at or after an ISO cutoff, newest first."""
        self._check_table(table_name)
        rows = self.execute_query(
            f"SELECT id, payload, status, received_at FROM {table_name} "  # noqa: S608
            "WHERE type=? AND received_at >= ? ORDER BY received_at DESC, id DESC",
            (job_type, cutoff),
            fetch_all=True,
        )
        return [dict(r) for r in rows or []]

    def cancel_running_job(
        self, job_id: int, completed_at: str, table_name: str = "jobs"
    ) -> int:
        """Mark a still-running job cancelled; returns rows changed (0 if it finished)."""
        self._check_table(table_name)
        return (
            self.execute_query(
                f"UPDATE {table_name} SET status='cancelled', completed_at=? "  # noqa: S608
                "WHERE id=? AND status='running'",
                (completed_at, job_id),
            )
            or 0
        )

    def update_progress(self, table_name: str, job_id: int, progress: int):
        self._check_table(table_name)
        self.execute_query(
            f"UPDATE {table_name} SET progress=? WHERE id=?",
            (progress, job_id),
        )

    # ----- per-phase timing -------------------------------------------------
    # An orchestrating module (poster_renamerr, asset_renamerr) records the
    # sub-steps it runs and their timing into the job's `phases` JSON column so
    # the Jobs page can show a per-phase timeline. Safe as read-modify-write:
    # a job runs in a single worker thread, so its own phases are never written
    # concurrently. Each phase: {name, status, started_at, finished_at,
    # duration_s}, status in pending|running|success|error|skipped.

    def _load_phases(self, table_name: str, job_id: int) -> list:
        row = self.execute_query(
            f"SELECT phases FROM {table_name} WHERE id=?", (job_id,), fetch_one=True
        )
        if not row or not row.get("phases"):
            return []
        try:
            return json.loads(row["phases"]) or []
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_phases(self, table_name: str, job_id: int, phases: list) -> None:
        self.execute_query(
            f"UPDATE {table_name} SET phases=? WHERE id=?",
            (json.dumps(phases), job_id),
        )

    def declare_phases(self, table_name: str, job_id: int, names: list) -> None:
        """Seed the ordered list of phases a run intends to execute as
        ``pending`` so the UI can show what's coming, not just what's done."""
        self._check_table(table_name)
        phases = [
            {
                "name": n,
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_s": None,
            }
            for n in names
        ]
        self._save_phases(table_name, job_id, phases)

    def start_phase(self, table_name: str, job_id: int, name: str) -> None:
        """Mark a phase ``running`` and stamp its start. Reuses the declared
        pending entry if present, else appends a new one."""
        self._check_table(table_name)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        phases = self._load_phases(table_name, job_id)
        entry = next(
            (
                p
                for p in phases
                if p.get("name") == name and p.get("status") == "pending"
            ),
            None,
        )
        if entry is None:
            entry = {"name": name, "finished_at": None, "duration_s": None}
            phases.append(entry)
        entry["status"] = "running"
        entry["started_at"] = now
        self._save_phases(table_name, job_id, phases)

    def finish_phase(
        self,
        table_name: str,
        job_id: int,
        name: str,
        status: str = "success",
        error: str = None,
    ) -> None:
        """Stamp a running phase's end + duration and set its final status."""
        self._check_table(table_name)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        phases = self._load_phases(table_name, job_id)
        # Most-recent running entry with this name (handles a re-run of the
        # same phase name within one job).
        entry = next(
            (
                p
                for p in reversed(phases)
                if p.get("name") == name and p.get("status") == "running"
            ),
            None,
        )
        if entry is None:
            return
        entry["status"] = status
        entry["finished_at"] = now
        if error:
            entry["error"] = str(error)[:500]
        try:
            start = datetime.datetime.fromisoformat(entry["started_at"])
            entry["duration_s"] = round(
                (datetime.datetime.fromisoformat(now) - start).total_seconds(), 1
            )
        except (ValueError, TypeError, KeyError):
            entry["duration_s"] = None
        self._save_phases(table_name, job_id, phases)

    def skip_pending_phases(self, table_name: str, job_id: int) -> None:
        """Mark any still-``pending`` phases ``skipped`` — called at the end of a
        run so a declared-but-not-reached phase doesn't linger as pending."""
        self._check_table(table_name)
        phases = self._load_phases(table_name, job_id)
        changed = False
        for p in phases:
            if p.get("status") == "pending":
                p["status"] = "skipped"
                changed = True
        if changed:
            self._save_phases(table_name, job_id, phases)

    def enqueue_job(
        self,
        table_name: str,
        payload: dict,
        job_type: str,
        extra_fields: dict = None,
        scheduled_at: str = None,
    ):
        """Add a new job to the specified table"""
        self._check_table(table_name)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fields = {
            "type": job_type,
            "received_at": now,
            "payload": json.dumps(payload),
            "status": "pending",
        }
        if scheduled_at:
            fields["scheduled_at"] = scheduled_at
        if extra_fields:
            fields.update(extra_fields)
        keys = ",".join(fields.keys())
        qs = ",".join("?" for _ in fields)

        try:
            with self.get_connection() as conn:
                # Dedupe module_run jobs by module_name. The SELECT runs
                # inside the same connection/transaction as the INSERT, so
                # two callers racing to enqueue the same module can't both
                # win — SQLite serialises writes and the second SELECT
                # will see the first INSERT. Webhook storms, manual UI
                # "Run now" overlapping a scheduled fire, and two scheduler
                # ticks racing past the orchestrator's running-check all
                # collapse to a single in-flight job per module.
                if job_type == "module_run":
                    module_name = (payload or {}).get("module_name")
                    if module_name:
                        existing = conn.execute(
                            f"SELECT id, status FROM {table_name} "
                            f"WHERE type = 'module_run' "
                            f"  AND status IN ('pending', 'running') "
                            f"  AND json_extract(payload, '$.module_name') = ?",
                            (module_name,),
                        ).fetchone()
                        if existing:
                            existing_id = existing["id"]
                            existing_status = existing["status"]
                            return {
                                "success": True,
                                "deduped": True,
                                "message": (
                                    f"module_run for {module_name} already "
                                    f"{existing_status} (job {existing_id}); "
                                    "skipped duplicate enqueue"
                                ),
                                "data": {"job_id": existing_id},
                            }

                # The Poster Cleanarr scans are idempotent cache-warmers; only
                # one of each needs to be in flight. Two scan clicks (or a page
                # mount racing the scan button) collapse to the same job so the
                # UI polls a single in-progress scan instead of stacking walks.
                if job_type in ("plex_metadata_scan", "kometa_assets_scan"):
                    existing = conn.execute(
                        f"SELECT id, status FROM {table_name} "
                        f"WHERE type = ? "
                        f"  AND status IN ('pending', 'running')",
                        (job_type,),
                    ).fetchone()
                    if existing:
                        existing_id = existing["id"]
                        existing_status = existing["status"]
                        return {
                            "success": True,
                            "deduped": True,
                            "message": (
                                f"{job_type} already {existing_status} "
                                f"(job {existing_id}); skipped duplicate enqueue"
                            ),
                            "data": {"job_id": existing_id},
                        }

                cursor = conn.execute(
                    f"INSERT INTO {table_name} ({keys}) VALUES ({qs})",
                    tuple(fields.values()),
                )
                job_id = cursor.lastrowid
                conn.commit()

            # Wake workers immediately
            self._job_event.set()

            return {
                "success": True,
                "message": "Job enqueued successfully",
                "data": {"job_id": job_id},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error enqueuing job: {e}",
                "error_code": "ENQUEUE_JOB_ERROR",
            }

    def get_job_by_id(self, table_name: str, job_id: int):
        self._check_table(table_name)
        row = self.execute_query(
            f"SELECT * FROM {table_name} WHERE id=?", (job_id,), fetch_one=True
        )
        return dict(row) if row else None

    def cleanup_jobs(self, table_name: str = "jobs", days: int = 30):
        """Delete old completed/failed jobs"""
        self._check_table(table_name)
        try:
            cutoff = (
                datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(days=days)
            ).isoformat()
            deleted = self.execute_query(
                f"DELETE FROM {table_name} WHERE status IN ('success', 'error') AND received_at < ?",
                (cutoff,),
            )

            if deleted > 0:
                log = self.logger.get_adapter("WORKER")
                log.info(
                    f"Removed {deleted} jobs from '{table_name}' older than {days} days"
                )

            return {
                "success": True,
                "message": f"Deleted {deleted} old jobs (> {days}d)",
                "data": {"deleted": deleted, "days": days},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error cleaning up jobs: {e}",
                "error_code": "DB_CLEANUP_JOBS_ERROR",
            }

    def _periodic_cleanup(self, table_name: str):
        """Run cleanup periodically"""
        while self._cleanup_running and not self._shutdown_event.is_set():
            try:
                self.cleanup_jobs(table_name, days=self.job_deletion_days)
            except Exception as ex:
                log = self.logger.get_adapter("WORKER")
                log.error(f"Periodic cleanup error: {ex}", exc_info=True)

            sleep_time = 10 if self._shutdown_requested else self.cleanup_interval
            if self._shutdown_event.wait(timeout=sleep_time):
                break

    def get_running_module_job(self, module_name: str, table_name: str = "jobs"):
        """Get running job for a specific module"""
        self._check_table(table_name)
        import json

        query = f"""SELECT id, status, payload FROM {table_name}
                    WHERE status='running' AND type='module_run'"""

        rows = self.execute_query(query, fetch_all=True)

        for row in rows or []:
            payload = json.loads(row["payload"])
            if payload.get("module_name") == module_name:
                return {
                    "job_id": row["id"],
                    "status": row["status"],
                    "origin": payload.get("origin", "unknown"),
                }

        return None

    def list_jobs(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
        job_type: str = None,
        module_name: str = None,
    ):
        """
        List jobs with DB-level filtering and pagination.

        Args:
            status: filter by status (pending/running/success/error/cancelled).
            limit: max rows to return.
            offset: rows to skip (applied at the SQL level, not post-fetch).
            job_type: filter by `type` column (e.g. "module_run", "webhook").
            module_name: filter module_run jobs whose JSON payload contains
                the given module. Applied post-fetch because SQLite JSON
                operators vary across builds.
        """
        try:
            clauses = []
            params = []
            if status:
                clauses.append("status=?")
                params.append(status)
            if job_type:
                clauses.append("type=?")
                params.append(job_type)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

            if module_name:
                # module_name lives in the JSON payload and can't be filtered in
                # SQL portably, so page through newest-first and post-filter until
                # we've collected enough matches (offset+limit) or the table is
                # exhausted. A single fixed over-fetch window would silently drop
                # matches when the module's runs are sparse among many other jobs.
                needed = offset + limit
                page_size = max(needed + 200, 500)
                sql = (
                    f"SELECT * FROM jobs {where} "
                    "ORDER BY received_at DESC LIMIT ? OFFSET ?"
                )
                matched: list = []
                sql_offset = 0
                while len(matched) < needed:
                    rows = self.execute_query(
                        sql, tuple(params) + (page_size, sql_offset), fetch_all=True
                    )
                    if not rows:
                        break  # table exhausted
                    for row in rows:
                        payload = row["payload"]
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except (json.JSONDecodeError, TypeError):
                                payload = {}
                        if (
                            isinstance(payload, dict)
                            and payload.get("module_name") == module_name
                        ):
                            matched.append(dict(row))
                    if len(rows) < page_size:
                        break  # short page → end of table
                    sql_offset += page_size
                jobs = matched[offset : offset + limit]
            else:
                sql = f"SELECT * FROM jobs {where} ORDER BY received_at DESC LIMIT ? OFFSET ?"
                rows = self.execute_query(
                    sql, tuple(params) + (limit, offset), fetch_all=True
                )
                jobs = [dict(row) for row in rows] if rows else []

            # Compute total for pagination. The JSON-filtered case can't give
            # an exact count without a full table scan; return None in that case.
            total: Optional[int] = None
            if not module_name:
                count_sql = f"SELECT COUNT(*) AS total FROM jobs {where}"
                total_row = self.execute_query(count_sql, tuple(params), fetch_one=True)
                total = total_row["total"] if total_row else 0

            return {
                "success": True,
                "message": f"Returned {len(jobs)} job(s)",
                "data": {
                    "jobs": jobs,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error listing jobs: {e}",
                "error_code": "DB_LIST_JOBS_ERROR",
            }

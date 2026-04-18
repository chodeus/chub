# util/scheduler.py

import time
from datetime import datetime
from logging import Logger
from typing import Any, Dict, Optional

from croniter import croniter
from dateutil import tz

from backend.util.helper import create_table

# Scheduler configuration constants
SCHEDULER_POLL_INTERVAL_SECONDS = 5
SCHEDULER_UPTIME_LOG_INTERVAL_SECONDS = 60
SCHEDULER_HEALTH_CHECK_INTERVAL_SECONDS = 6 * 3600  # every 6h
SCHEDULER_HEALTH_RETENTION_DAYS = 30

# Persistent cache for cron next-run times (must survive across check_schedule calls)
_next_run_times: Dict[str, datetime] = {}


def check_schedule(script_name: str, schedule: str, logger: Optional[Logger]) -> bool:
    """Check if the current time matches the given schedule for a script."""
    try:
        now: datetime = datetime.now()
        try:
            frequency, data = schedule.split("(")
        except ValueError:
            logger.error(
                f"Invalid schedule format: {schedule} for script: {script_name}"
            )
            return False
        data = data[:-1]

        if frequency == "hourly":
            return int(data) == now.minute

        if frequency == "daily":
            times = data.split("|")
            for time_ in times:
                hour, minute = map(int, time_.split(":"))
                if now.hour == hour and now.minute == minute:
                    return True

        if frequency == "weekly":
            days = [day.split("@")[0] for day in data.split("|")]
            times = [day.split("@")[1] for day in data.split("|")]
            current_day = now.strftime("%A").lower()
            for day, time_ in zip(days, times):
                hour, minute = map(int, time_.split(":"))
                if current_day == day or (
                    current_day == "sunday" and day == "saturday"
                ):
                    if now.hour == hour and now.minute == minute:
                        return True

        if frequency == "monthly":
            day_str, time_str = data.split("@")
            day = int(day_str)
            hour, minute = map(int, time_str.split(":"))
            if now.day == day and now.hour == hour and now.minute == minute:
                return True

        if frequency == "range":
            ranges = data.split("|")
            for start_end in ranges:
                start, end = start_end.split("-")
                start_month, start_day = map(int, start.split("/"))
                end_month, end_day = map(int, end.split("/"))
                start_date = datetime(now.year, start_month, start_day)
                end_date = datetime(now.year, end_month, end_day)
                if start_date <= now <= end_date:
                    return True

        if frequency == "cron":
            local_tz = tz.tzlocal()
            local_date = datetime.now(local_tz)
            current_time = local_date.replace(second=0, microsecond=0)
            next_run = _next_run_times.get(script_name)
            if next_run is None:
                next_run = croniter(data, local_date).get_next(datetime)
                _next_run_times[script_name] = next_run
                logger.debug(f"Next run for {script_name}: {next_run}")
            if next_run <= current_time:
                _next_run_times[script_name] = croniter(data, local_date).get_next(datetime)
                logger.debug(f"Cron triggered for {script_name}, next run: {_next_run_times[script_name]}")
                return True
            return False

        return False

    except ValueError as e:
        logger.error(f"Invalid schedule: {schedule} for script: {script_name}")
        logger.error(f"Error: {e}", exc_info=True)
        return False


def print_schedule_table(logger: Optional[Any], schedule: Dict[str, str]) -> None:
    """Print the current schedule table using util.helper.create_table for consistency."""
    if logger is None:
        return
    table_data = [["Module", "Schedule"]] + [
        [module_name, schedule_time] for module_name, schedule_time in schedule.items()
    ]
    logger.info(create_table(table_data))


class ChubScheduler:
    """Pure scheduling logic - delegates execution to ModuleOrchestrator via job queue"""

    def __init__(
        self, config: Any, logger: Optional[Any], module_orchestrator: Any
    ) -> None:
        self.config = config
        self.logger = logger
        self.module_orchestrator = module_orchestrator
        self.running = False
        self._last_health_check: float = 0.0

    def start(self) -> None:
        """Start the scheduler loop"""
        schedule = self.config.schedule

        if self.logger:
            self.logger.get_adapter("SCHEDULER").info("Starting scheduler loop...")
            log_adapter = self.logger.get_adapter("SCHEDULER")
        else:
            print("[SCHEDULER] Starting scheduler loop...")
            log_adapter = None

        print_schedule_table(log_adapter, schedule)

        if self.logger:
            self.logger.get_adapter("SCHEDULER").info(
                "Waiting for scheduled modules..."
            )
        else:
            print("[SCHEDULER] Waiting for scheduled modules...")

        self.running = True
        start_time = time.monotonic()

        try:
            while self.running:
                self._tick(schedule)
                self._system_tick()
                time.sleep(SCHEDULER_POLL_INTERVAL_SECONDS)

                # Periodic uptime log
                elapsed = int(time.monotonic() - start_time)
                if elapsed % SCHEDULER_UPTIME_LOG_INTERVAL_SECONDS == 0:
                    minutes = elapsed // 60
                    seconds = elapsed % 60
                    if self.logger:
                        self.logger.get_adapter("SCHEDULER").debug(
                            f"Scheduler is alive. Uptime: {minutes}m {seconds}s"
                        )
        except Exception as e:
            import traceback

            if self.logger:
                self.logger.get_adapter("SCHEDULER").error(
                    f"FATAL error in scheduler loop: {e}", exc_info=True
                )
            else:
                print(f"[SCHEDULER] FATAL error: {e}")
            traceback.print_exc()
            raise
        finally:
            if self.logger:
                self.logger.get_adapter("SCHEDULER").info("Scheduler loop ended")
            else:
                print("[SCHEDULER] Scheduler loop ended")

    def stop(self) -> None:
        """Stop the scheduler"""
        self.running = False

    def _tick(self, schedule: Dict[str, str]) -> None:
        """Check for due modules and queue them for execution"""
        try:
            for name, sched in schedule.items():
                if not sched:
                    continue

                # Skip if already running (check via orchestrator)
                status = self.module_orchestrator.get_module_status(name)
                if status["running"]:
                    continue

                # Check if module should run
                log_adapter = (
                    self.logger.get_adapter("scheduler") if self.logger else None
                )
                if check_schedule(name, sched, log_adapter):
                    if self.logger:
                        self.logger.get_adapter("SCHEDULER").info(
                            f"Running scheduled module: {name}"
                        )
                    else:
                        print(f"[SCHEDULER] Running scheduled module: {name}")

                    # Queue module for async execution
                    result = self.module_orchestrator.run_module_async(
                        name, "scheduled"
                    )

                    if not result["success"]:
                        if self.logger:
                            self.logger.get_adapter("SCHEDULER").error(
                                f"Failed to queue module {name}: {result['message']}"
                            )
                        else:
                            print(
                                f"[SCHEDULER] Failed to queue module {name}: {result['message']}"
                            )

        except Exception as e:
            if self.logger:
                self.logger.get_adapter("SCHEDULER").error(
                    f"Exception in tick(): {e}", exc_info=True
                )
            else:
                print(f"[SCHEDULER] Exception in tick(): {e}")
            raise

    def _system_tick(self) -> None:
        """
        Built-in periodic tasks that don't need a config entry: probe instance
        health every 6h and write a snapshot row. The snapshots feed the
        dashboard and digest endpoints. Failures here must never crash the
        scheduler loop.
        """
        now = time.monotonic()
        if now - self._last_health_check < SCHEDULER_HEALTH_CHECK_INTERVAL_SECONDS:
            return
        self._last_health_check = now

        try:
            self._write_health_snapshot()
            self._prune_old_health_snapshots()
        except Exception as e:
            if self.logger:
                self.logger.get_adapter("SCHEDULER").error(
                    f"System tick error: {e}", exc_info=True
                )

    def _write_health_snapshot(self) -> None:
        import requests

        from backend.util.database import ChubDB
        from backend.util.ssrf_guard import is_safe_url

        now_iso = datetime.now().isoformat()
        rows = []
        for service in ("plex", "radarr", "sonarr", "lidarr"):
            instances = getattr(self.config.instances, service, {})
            for name, details in instances.items():
                url = details.url.rstrip("/") if details.url else ""
                api = details.api or ""
                if not url:
                    continue
                if service == "plex":
                    test_url = f"{url}/library/sections"
                    headers = {"X-Plex-Token": api} if api else {}
                else:
                    api_ver = "v1" if service == "lidarr" else "v3"
                    test_url = f"{url}/api/{api_ver}/system/status"
                    headers = {"X-Api-Key": api} if api else {}

                safe, reason = is_safe_url(test_url)
                if not safe:
                    rows.append(
                        (now_iso, service, name, "blocked", None, None, reason)
                    )
                    continue

                import time as _t
                start = _t.time()
                try:
                    resp = requests.get(test_url, headers=headers, timeout=3)
                    elapsed = int((_t.time() - start) * 1000)
                    rows.append((
                        now_iso,
                        service,
                        name,
                        "healthy" if resp.ok else "unhealthy",
                        resp.status_code,
                        elapsed,
                        None,
                    ))
                except requests.exceptions.Timeout:
                    rows.append((now_iso, service, name, "timeout", None, 3000, None))
                except requests.exceptions.ConnectionError:
                    rows.append((now_iso, service, name, "unreachable", None, None, None))
                except Exception as exc:
                    rows.append((now_iso, service, name, "error", None, None, str(exc)))

        if not rows:
            return
        with ChubDB(logger=self.logger, quiet=True) as db:
            for row in rows:
                try:
                    db.worker.execute_query(
                        "INSERT INTO system_health_snapshots "
                        "(snapshot_at, service, instance_name, status, status_code, response_time_ms, error) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                except Exception:
                    pass

    def _prune_old_health_snapshots(self) -> None:
        from datetime import timedelta

        from backend.util.database import ChubDB

        cutoff = (datetime.now() - timedelta(days=SCHEDULER_HEALTH_RETENTION_DAYS)).isoformat()
        try:
            with ChubDB(logger=self.logger, quiet=True) as db:
                db.worker.execute_query(
                    "DELETE FROM system_health_snapshots WHERE snapshot_at < ?",
                    (cutoff,),
                )
        except Exception:
            pass

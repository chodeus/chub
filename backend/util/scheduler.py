# util/scheduler.py

import threading
import time
from datetime import datetime
from logging import Logger
from typing import Any, Dict, List, Optional

from croniter import croniter
from dateutil import tz

from backend.util.helper import create_table

# Scheduler configuration constants
SCHEDULER_POLL_INTERVAL_SECONDS = 5
SCHEDULER_UPTIME_LOG_INTERVAL_SECONDS = 600
SCHEDULER_HEALTH_CHECK_INTERVAL_SECONDS = 6 * 3600  # every 6h
SCHEDULER_HEALTH_RETENTION_DAYS = 30

# Persistent cache for cron next-run times (must survive across check_schedule calls)
_next_run_times: Dict[str, datetime] = {}

# Last minute a non-cron schedule fired per script, so the tick (which can run
# several times within the matched minute) triggers it at most once per window.
_last_fired: Dict[str, datetime] = {}

_WEEKDAY_ALIASES = {
    "0": "sunday",
    "7": "sunday",
    "sun": "sunday",
    "sunday": "sunday",
    "1": "monday",
    "mon": "monday",
    "monday": "monday",
    "2": "tuesday",
    "tue": "tuesday",
    "tues": "tuesday",
    "tuesday": "tuesday",
    "3": "wednesday",
    "wed": "wednesday",
    "wednesday": "wednesday",
    "4": "thursday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "thursday": "thursday",
    "5": "friday",
    "fri": "friday",
    "friday": "friday",
    "6": "saturday",
    "sat": "saturday",
    "saturday": "saturday",
}


def _safe_md_date(year: int, month: int, day: int) -> datetime:
    """datetime for a month/day range boundary, clamping Feb 29 to Feb 28 on
    non-leap years so a leap-day range doesn't silently never fire."""
    try:
        return datetime(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return datetime(year, 2, 28)
        raise


def _normalize_weekday(day: str) -> str:
    return _WEEKDAY_ALIASES.get(day.strip().lower(), day.strip().lower())


def _iter_weekly_entries(data: str):
    """Yield (weekday, time) from both `mon@09|fri@09` and `Mon,Fri@09`."""
    for part in data.split("|"):
        if "@" not in part:
            continue
        raw_days, time_ = part.split("@", 1)
        for day in raw_days.split(","):
            normalized = _normalize_weekday(day)
            if normalized:
                yield normalized, time_


def _iter_monthly_entries(data: str):
    """Yield (monthday, time) from both `1@09|15@09` and `1,15@09`."""
    for part in data.split("|"):
        if "@" not in part:
            continue
        raw_days, time_ = part.split("@", 1)
        for day in raw_days.split(","):
            yield day.strip(), time_


class _SilentLogger:
    """Stand-in when no logger is supplied — check_schedule logs
    opportunistically and must not crash on logger=None."""

    def debug(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


_SILENT_LOGGER = _SilentLogger()


def check_schedule(script_name: str, schedule: str, logger: Optional[Logger]) -> bool:
    """Check if the current time matches the given schedule for a script."""
    logger = logger or _SILENT_LOGGER
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
            current_day = now.strftime("%A").lower()
            for day, time_ in _iter_weekly_entries(data):
                hour, minute = map(int, time_.split(":"))
                if current_day == day:
                    if now.hour == hour and now.minute == minute:
                        return True

        if frequency == "monthly":
            for day_str, time_str in _iter_monthly_entries(data):
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
                start_date = _safe_md_date(now.year, start_month, start_day)
                end_date = _safe_md_date(now.year, end_month, end_day)
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
                _next_run_times[script_name] = croniter(data, local_date).get_next(
                    datetime
                )
                logger.debug(
                    f"Cron triggered for {script_name}, next run: {_next_run_times[script_name]}"
                )
                return True
            return False

        return False

    except ValueError as e:
        logger.error(f"Invalid schedule: {schedule} for script: {script_name}")
        logger.error(f"Error: {e}", exc_info=True)
        return False


def cron_next_run(
    schedule: Optional[str], now: Optional[datetime] = None
) -> Optional[datetime]:
    """Compute the next fire time for a ``cron(...)`` schedule.

    Stateless on purpose — unlike :func:`check_schedule` it never touches the
    ``_next_run_times`` trigger cache, so it is safe to call from API handlers
    that only want to display the upcoming run. Returns ``None`` for non-cron,
    empty, or invalid schedules (the frontend computes the other frequencies).
    """
    if not schedule or not schedule.startswith("cron(") or not schedule.endswith(")"):
        return None
    expr = schedule[len("cron(") : -1].strip()
    if not expr:
        return None
    try:
        base = now or datetime.now(tz.tzlocal())
        return croniter(expr, base).get_next(datetime)
    except (ValueError, KeyError):
        return None


def print_schedule_table(logger: Optional[Any], schedule: Dict[str, str]) -> None:
    """Print scheduled modules in a table and list unscheduled ones on a single line."""
    if logger is None:
        return

    scheduled = [
        (name, value)
        for name, value in schedule.items()
        if value not in (None, "", "None")
    ]
    unscheduled = [
        name for name, value in schedule.items() if value in (None, "", "None")
    ]

    if scheduled:
        table_data = [["Module", "Schedule"]] + [
            [name, value] for name, value in scheduled
        ]
        logger.info(create_table(table_data))
    else:
        logger.info("No modules are currently scheduled.")

    if unscheduled:
        logger.info(f"Unscheduled: {', '.join(unscheduled)}")


def _profile_value(profile: Any, key: str, default: Any = None) -> Any:
    if isinstance(profile, dict):
        return profile.get(key, default)
    return getattr(profile, key, default)


def _profile_to_dict(profile: Any) -> Dict[str, Any]:
    if isinstance(profile, dict):
        return dict(profile)
    if hasattr(profile, "model_dump"):
        return profile.model_dump(mode="python")
    if hasattr(profile, "__dict__"):
        return dict(vars(profile))
    return {}


def _upgradinatorr_profile_label(profile: Any, index: int) -> str:
    return (
        _profile_value(profile, "label", "")
        or _profile_value(profile, "instance", "")
        or f"profile_{index + 1}"
    )


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
        if self.logger:
            self.logger.get_adapter("SCHEDULER").info("Starting scheduler loop...")
            log_adapter = self.logger.get_adapter("SCHEDULER")
        else:
            print("[SCHEDULER] Starting scheduler loop...")
            log_adapter = None

        print_schedule_table(log_adapter, self.config.schedule)

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
                self._tick(self.config.schedule)
                self._system_tick()
                time.sleep(SCHEDULER_POLL_INTERVAL_SECONDS)

                # Periodic uptime log — emit via heartbeat() so the
                # frontend Logs page hides it by default.
                elapsed = int(time.monotonic() - start_time)
                if elapsed % SCHEDULER_UPTIME_LOG_INTERVAL_SECONDS == 0:
                    minutes = elapsed // 60
                    seconds = elapsed % 60
                    if self.logger:
                        self.logger.get_adapter("SCHEDULER").heartbeat(
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
            # Hard-disabled modules (Modules page) never auto-run.
            from backend.util.config import load_config

            inst_sync_schedule = ""
            try:
                cfg = load_config()
                disabled = set(getattr(cfg.general, "disabled_modules", None) or [])
                inst_sync_schedule = getattr(cfg.instances, "sync_schedule", "") or ""
            except Exception:
                disabled = set()

            queued_modules = set()
            for name, sched in schedule.items():
                if not sched:
                    continue
                if name in disabled:
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
                    # check_schedule is a pure match and stays True for the whole
                    # minute; the tick can run several times within it, so fire
                    # each module at most once per matched minute.
                    minute_now = datetime.now().replace(second=0, microsecond=0)
                    if _last_fired.get(name) == minute_now:
                        continue
                    _last_fired[name] = minute_now

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
                    else:
                        queued_modules.add(name)

            self._tick_upgradinatorr_profiles(queued_modules)
            self._tick_schedule_blocks(queued_modules)
            self._tick_media_sync(inst_sync_schedule)

        except Exception as e:
            if self.logger:
                self.logger.get_adapter("SCHEDULER").error(
                    f"Exception in tick(): {e}", exc_info=True
                )
            else:
                print(f"[SCHEDULER] Exception in tick(): {e}")
            raise

    def _tick_media_sync(self, sync_schedule: str) -> None:
        """Queue the background media-cache reconciliation when its
        Instances-page schedule (config.instances.sync_schedule) is due.

        It runs as a plain ``media_sync`` job — stepping through each instance
        sequentially and logging to General — NOT as a user module, so it never
        appears on the Modules/Logs pages. A cron schedule string is used so
        check_schedule's per-name next-run guard prevents double-firing.
        """
        if not sync_schedule:
            return
        log_adapter = self.logger.get_adapter("SCHEDULER") if self.logger else None
        try:
            if not check_schedule("media_sync", sync_schedule, log_adapter):
                return
            db = getattr(self.module_orchestrator, "db", None)
            if db is None:
                return
            result = db.worker.enqueue_job(
                "jobs", {"origin": "scheduled"}, job_type="media_sync"
            )
            if log_adapter:
                if result.get("success"):
                    log_adapter.info("Queued media-cache reconciliation (media_sync)")
                else:
                    log_adapter.error(
                        f"Failed to queue media_sync: {result.get('message')}"
                    )
        except Exception as e:
            if log_adapter:
                log_adapter.error(f"media_sync tick failed: {e}", exc_info=True)

    def _tick_upgradinatorr_profiles(self, queued_modules: set) -> None:
        """Queue Upgradinatorr profile-specific schedules."""
        if "upgradinatorr" in queued_modules:
            return

        upgradinatorr_config = getattr(self.config, "upgradinatorr", None)
        profiles = getattr(upgradinatorr_config, "instances_list", None) or []
        if not profiles:
            return

        log_adapter = self.logger.get_adapter("scheduler") if self.logger else None
        due_profiles: List[Dict[str, Any]] = []
        due_labels: List[str] = []

        for index, profile in enumerate(profiles):
            if not _profile_value(profile, "enabled", True):
                continue
            sched = _profile_value(profile, "schedule", "")
            if not sched:
                continue

            label = _upgradinatorr_profile_label(profile, index)
            schedule_key = f"upgradinatorr:{index}:{label}"
            if check_schedule(schedule_key, sched, log_adapter):
                due_profiles.append(_profile_to_dict(profile))
                due_labels.append(label)

        if not due_profiles:
            return

        status = self.module_orchestrator.get_module_status("upgradinatorr")
        if status["running"]:
            return

        if self.logger:
            self.logger.get_adapter("SCHEDULER").info(
                "Running scheduled Upgradinatorr profile(s): " + ", ".join(due_labels)
            )
        else:
            print(
                "[SCHEDULER] Running scheduled Upgradinatorr profile(s): "
                + ", ".join(due_labels)
            )

        result = self.module_orchestrator.run_module_async(
            "upgradinatorr",
            "scheduled:upgradinatorr_profiles",
            overrides={"instances_list": due_profiles},
        )

        if not result["success"]:
            if self.logger:
                self.logger.get_adapter("SCHEDULER").error(
                    f"Failed to queue Upgradinatorr profiles: {result['message']}"
                )
            else:
                print(
                    f"[SCHEDULER] Failed to queue Upgradinatorr profiles: {result['message']}"
                )

    def _tick_schedule_blocks(self, queued_modules: set) -> None:
        """Queue module runs from multi-block schedules (config.schedule_blocks).

        Each block fires on its own schedule string and injects its `overrides`
        into the run (e.g. one block reports daily, another removes weekly).
        Blocks for a module already queued this tick — or already running — are
        skipped; if several blocks for one module are due at the same minute,
        their overrides are merged (later blocks win). The per-block schedule
        key keeps each block's cron next-run cache independent.
        """
        blocks_by_module = getattr(self.config, "schedule_blocks", None) or {}
        if not blocks_by_module:
            return

        log_adapter = self.logger.get_adapter("scheduler") if self.logger else None

        for module_name, blocks in blocks_by_module.items():
            if module_name in queued_modules or not blocks:
                continue

            status = self.module_orchestrator.get_module_status(module_name)
            if status["running"]:
                continue

            merged_overrides: Dict[str, Any] = {}
            due_labels: List[str] = []
            for index, block in enumerate(blocks):
                if not _profile_value(block, "enabled", True):
                    continue
                sched = _profile_value(block, "schedule", "")
                if not sched:
                    continue
                label = _profile_value(block, "label", "") or f"block {index + 1}"
                schedule_key = f"{module_name}:block:{index}:{label}"
                if check_schedule(schedule_key, sched, log_adapter):
                    overrides = _profile_value(block, "overrides", {}) or {}
                    if isinstance(overrides, dict):
                        merged_overrides.update(overrides)
                    due_labels.append(label)

            if not due_labels:
                continue

            if self.logger:
                self.logger.get_adapter("SCHEDULER").info(
                    f"Running scheduled {module_name} block(s): "
                    + ", ".join(due_labels)
                )
            else:
                print(
                    f"[SCHEDULER] Running scheduled {module_name} block(s): "
                    + ", ".join(due_labels)
                )

            result = self.module_orchestrator.run_module_async(
                module_name,
                f"scheduled:blocks:{','.join(due_labels)}",
                overrides=merged_overrides or None,
            )
            if not result["success"]:
                if self.logger:
                    self.logger.get_adapter("SCHEDULER").error(
                        f"Failed to queue {module_name} blocks: {result['message']}"
                    )
                else:
                    print(
                        f"[SCHEDULER] Failed to queue {module_name} blocks: "
                        f"{result['message']}"
                    )
                continue
            queued_modules.add(module_name)

    def _system_tick(self) -> None:
        """
        Built-in periodic tasks that don't need a config entry: probe instance
        health every 6h and write a snapshot row. The snapshots feed the
        dashboard and digest endpoints. Failures here must never crash the
        scheduler loop.

        The health probe hits every configured Plex/ARR instance with a short
        HTTP GET, so we run it in a daemon thread — otherwise N instances
        times 3s timeout blocks the main scheduler tick loop.
        """
        now = time.monotonic()
        if now - self._last_health_check < SCHEDULER_HEALTH_CHECK_INTERVAL_SECONDS:
            return
        self._last_health_check = now

        def _run() -> None:
            try:
                self._write_health_snapshot()
                self._prune_old_health_snapshots()
            except Exception as e:
                if self.logger:
                    self.logger.get_adapter("SCHEDULER").error(
                        f"System tick error: {e}", exc_info=True
                    )

        threading.Thread(target=_run, name="chub-health-snapshot", daemon=True).start()

    def _write_health_snapshot(self) -> None:
        import time as _t
        from concurrent.futures import ThreadPoolExecutor

        import requests

        from backend.util.database import ChubDB
        from backend.util.ssrf_guard import is_safe_url

        now_iso = datetime.now().isoformat()
        rows = []
        probes = []  # (service, name, test_url, headers) for reachable targets
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
                    rows.append((now_iso, service, name, "blocked", None, None, reason))
                    continue

                probes.append((service, name, test_url, headers))

        # Probe instances concurrently — each requests.get opens its own
        # connection, so this is thread-safe, and one slow/timing-out instance
        # no longer serializes a 3s wait per instance.
        def _probe(probe):
            service, name, test_url, headers = probe
            start = _t.time()
            try:
                resp = requests.get(test_url, headers=headers, timeout=3)
                elapsed = int((_t.time() - start) * 1000)
                return (
                    now_iso,
                    service,
                    name,
                    "healthy" if resp.ok else "unhealthy",
                    resp.status_code,
                    elapsed,
                    None,
                )
            except requests.exceptions.Timeout:
                return (now_iso, service, name, "timeout", None, 3000, None)
            except requests.exceptions.ConnectionError:
                return (now_iso, service, name, "unreachable", None, None, None)
            except Exception as exc:
                return (now_iso, service, name, "error", None, None, str(exc))

        if probes:
            with ThreadPoolExecutor(max_workers=min(10, len(probes))) as pool:
                rows.extend(pool.map(_probe, probes))

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

        cutoff = (
            datetime.now() - timedelta(days=SCHEDULER_HEALTH_RETENTION_DAYS)
        ).isoformat()
        try:
            with ChubDB(logger=self.logger, quiet=True) as db:
                db.worker.execute_query(
                    "DELETE FROM system_health_snapshots WHERE snapshot_at < ?",
                    (cutoff,),
                )
        except Exception:
            pass

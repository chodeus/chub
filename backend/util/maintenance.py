"""Background maintenance: daily auto-backup and log pruning.

A single daemon thread (started from the FastAPI lifespan) wakes once a day and,
driven entirely by `general` config, optionally:
  - writes a config+db backup and trims the backups directory, and
  - deletes rotated log files older than the retention window.

Both tasks are no-ops unless enabled in config, so the thread is cheap to leave
running. All work is wrapped so a transient failure never kills the thread.
"""

import os
import stat
import threading
import time
from pathlib import Path

from backend.util.backup import get_backup_dir, save_backup


def _log_base() -> Path:
    """Resolve the logs base directory the same way the logger does."""
    base = os.getenv("LOG_DIR")
    if base:
        return Path(base)
    return Path(__file__).resolve().parents[2] / "logs"


def prune_old_logs(retention_days: int, logger=None) -> int:
    """Delete rotated log files older than `retention_days`. Returns the count.

    A retention of 0 (or less) disables time-based pruning entirely — count-based
    rotation via `max_logs` still applies. Returns 0 in that case.
    """
    if not retention_days or retention_days <= 0:
        return 0

    base = _log_base()
    if not base.exists():
        return 0

    cutoff = time.time() - retention_days * 86400
    removed = 0
    for log_file in base.rglob("*.log"):
        try:
            if log_file.is_file() and log_file.stat().st_mtime < cutoff:
                log_file.unlink()
                removed += 1
        except OSError as e:
            if logger:
                logger.debug(f"Could not prune log {log_file}: {e}")
    if removed and logger:
        logger.info(f"Pruned {removed} log file(s) older than {retention_days} day(s)")
    return removed


def prune_old_backups(backup_dir: Path, keep: int, logger=None) -> int:
    """Keep only the newest `keep` chub-backup archives. Returns the count removed."""
    if keep <= 0:
        return 0
    try:
        backups = sorted(
            backup_dir.glob("chub-backup-*.zip"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return 0

    try:
        root = backup_dir.resolve(strict=True)
        dir_fd = os.open(str(root), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return 0

    removed = 0
    try:
        for old in backups[keep:]:
            try:
                # NEVER resolve-then-unlink: that deletes a symlink's TARGET.
                # lstat + S_ISREG rejects links and dirs; unlinking by name
                # against dir_fd stops a swapped parent redirecting the delete.
                st = os.lstat(os.path.join(str(root), old.name))
                if not stat.S_ISREG(st.st_mode):
                    if logger:
                        logger.warning(f"Skipping non-regular backup entry: {old}")
                    continue
                os.unlink(old.name, dir_fd=dir_fd)
                removed += 1
            except OSError as e:
                if logger:
                    logger.debug(f"Could not prune backup {old}: {e}")
    finally:
        os.close(dir_fd)
    if removed and logger:
        logger.info(f"Pruned {removed} old backup(s), keeping newest {keep}")
    return removed


def run_auto_backup(keep: int, logger=None) -> None:
    """Write one backup and trim the directory to `keep` archives."""
    save_backup(logger)
    prune_old_backups(get_backup_dir(logger), keep, logger)


def _run_once(config, logger) -> None:
    """One maintenance pass driven by current config."""
    general = getattr(config, "general", None)
    if general is None:
        return
    try:
        if getattr(general, "auto_backup", False):
            run_auto_backup(getattr(general, "auto_backup_keep", 12), logger)
    except Exception as e:
        if logger:
            logger.error(f"Auto-backup failed: {e}")
    try:
        prune_old_logs(getattr(general, "log_retention_days", 0), logger)
    except Exception as e:
        if logger:
            logger.error(f"Log pruning failed: {e}")


def start_maintenance(config, logger, interval: int = 86400) -> threading.Thread:
    """Start the daily maintenance daemon thread and return it.

    Config is loaded fresh each pass (the reference on config-reload is replaced,
    not mutated) so settings changes take effect without a restart. The first
    pass runs after `interval` so a just-restarted container doesn't back up on
    every boot.
    """

    def loop():
        while True:
            time.sleep(interval)
            try:
                from backend.util.config import load_config

                current = load_config()
            except Exception:
                current = config
            _run_once(current, logger)

    thread = threading.Thread(target=loop, name="maintenance", daemon=True)
    thread.start()
    if logger:
        logger.debug("Maintenance thread started (auto-backup + log pruning)")
    return thread

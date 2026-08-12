"""Background maintenance: daily auto-backup and log pruning.

A single daemon thread (started from the FastAPI lifespan) wakes once a day and,
driven entirely by `general` config, optionally:
  - writes a config+db backup and trims the backups directory, and
  - deletes rotated log files older than the retention window.

Both tasks are no-ops unless enabled in config, so the thread is cheap to leave
running. All work is wrapped so a transient failure never kills the thread.
"""

import fnmatch
import os
import stat
import threading
import time
from pathlib import Path

from backend.util.backup import get_backup_dir, save_backup
from backend.util.config import load_config
from backend.util.path_safety import is_path_allowed


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


def prune_old_backups(backup_dir: Path, keep: int, config, logger=None) -> int:
    """Keep only the newest `keep` chub-backup archives; returns the count removed.
    `config` is REQUIRED — it re-confines the RESOLVED root right before deleting."""
    if keep <= 0:
        return 0

    try:
        root = backup_dir.resolve(strict=True)
    except OSError:
        return 0

    # Authorise BEFORE opening anything: a component of backup_dir can be
    # re-pointed after get_backup_dir() cleared it, so resolve() may land out.
    if not is_path_allowed(str(root), config):
        if logger:
            logger.error(f"Refusing to prune '{root}': outside the allowed roots")
        return 0

    try:
        dir_fd = os.open(str(root), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return 0

    removed = 0
    try:
        # The path can be swapped between the check and the open, so pin the
        # descriptor to the directory that was actually authorised.
        opened, authorised = os.fstat(dir_fd), os.stat(root)
        if (opened.st_dev, opened.st_ino) != (authorised.st_dev, authorised.st_ino):
            if logger:
                logger.error(f"Refusing to prune '{root}': it changed under us")
            return 0

        entries = []
        for name in os.listdir(dir_fd):
            if not fnmatch.fnmatch(name, "chub-backup-*.zip"):
                continue
            try:
                # ONE nofollow stat through dir_fd: following a link to read
                # its mtime would stat a target the link owner chose.
                st = os.lstat(name, dir_fd=dir_fd)
            except OSError as e:
                if logger:
                    logger.debug(f"Could not read backup {root / name}: {e}")
                continue
            entries.append((st.st_mtime, name, stat.S_ISREG(st.st_mode)))
        entries.sort(key=lambda entry: entry[0], reverse=True)

        for _mtime, name, is_regular in entries[keep:]:
            # NEVER resolve-then-unlink: that deletes a symlink's TARGET.
            # S_ISREG rejects links/dirs; dir_fd anchors the unlink.
            if not is_regular:
                if logger:
                    logger.warning(f"Skipping non-regular backup entry: {root / name}")
                continue
            try:
                os.unlink(name, dir_fd=dir_fd)
                removed += 1
            except OSError as e:
                if logger:
                    logger.debug(f"Could not prune backup {root / name}: {e}")
    except OSError:
        return removed
    finally:
        os.close(dir_fd)
    if removed and logger:
        logger.info(f"Pruned {removed} old backup(s), keeping newest {keep}")
    return removed


def run_auto_backup(keep: int, logger=None) -> None:
    """Write one backup and trim the directory to `keep` archives."""
    save_backup(logger)
    root = get_backup_dir(logger)
    prune_old_backups(root, keep, load_config(), logger)


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


def start_maintenance(logger, interval: int = 86400) -> threading.Thread:
    """Start the daily maintenance daemon thread and return it. Config is loaded
    fresh each pass; the first pass waits `interval` (no backup on every boot)."""

    def loop():
        """Wake once per `interval` and run a pass against freshly loaded config."""
        while True:
            time.sleep(interval)
            try:
                current = load_config()
            except Exception as e:
                # Never fall back to the startup snapshot: these passes delete
                # files, and stale retention/paths would delete the wrong ones.
                if logger:
                    logger.warning(f"Maintenance pass skipped, config unreadable: {e}")
                continue
            _run_once(current, logger)

    thread = threading.Thread(target=loop, name="maintenance", daemon=True)
    thread.start()
    if logger:
        logger.debug("Maintenance thread started (auto-backup + log pruning)")
    return thread

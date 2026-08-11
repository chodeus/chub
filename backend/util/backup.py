"""Config + database backup archives.

Owns where backups go and how they're built, so both the /api/backup routes and
the maintenance thread can use them without either importing the other.
"""

import io
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.util.config import get_config_path, load_config
from backend.util.path_safety import is_path_allowed


def _get_db_path() -> str:
    """Get the SQLite database path."""
    config_dir = os.environ.get("CONFIG_DIR") or str(
        Path(__file__).parents[2] / "config"
    )
    return os.path.join(config_dir, "chub.db")


def _default_backup_dir() -> Path:
    """Fallback backup location: CONFIG_DIR/backups."""
    config_dir = os.environ.get("CONFIG_DIR") or str(
        Path(__file__).parents[2] / "config"
    )
    return Path(config_dir) / "backups"


def get_backup_dir(logger: Any = None) -> Path:
    """Resolve general.backup_dir, falling back to CONFIG_DIR/backups."""
    default = _default_backup_dir()

    configured = ""
    config = None
    try:
        config = load_config()
        configured = (getattr(config.general, "backup_dir", "") or "").strip()
    except Exception as exc:
        if logger:
            logger.error(f"Could not read backup_dir from config: {exc}")

    if configured and config is not None:
        if not is_path_allowed(configured, config):
            if logger:
                logger.error(
                    f"backup_dir '{configured}' is outside the allowed roots; "
                    f"backing up to {default} instead"
                )
        else:
            try:
                target = Path(configured).expanduser().resolve()
                target.mkdir(parents=True, exist_ok=True)
                # Re-confine the RESOLVED target: is_path_allowed() authorised a
                # path that a swapped symlink could since have re-pointed.
                if is_path_allowed(str(target), config):
                    return target
                if logger:
                    logger.error(
                        f"backup_dir '{configured}' resolved outside the allowed "
                        f"roots ({target}); backing up to {default} instead"
                    )
            except OSError as exc:
                if logger:
                    logger.error(
                        f"backup_dir '{configured}' is not usable ({exc}); "
                        f"backing up to {default} instead"
                    )

    default.mkdir(parents=True, exist_ok=True)
    return default


def build_backup_bytes() -> bytes:
    """Backup zip (config.yml + chub.db.sql dump) bytes; SQLite backup API snapshots
    the db safely while in use. Shared by the download endpoint + maintenance thread."""
    config_path = get_config_path()
    db_path = _get_db_path()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(config_path):
            zf.write(config_path, "config.yml")

        if os.path.exists(db_path):
            db_buf = io.BytesIO()
            src = sqlite3.connect(db_path)
            try:
                mem = sqlite3.connect(":memory:")
                src.backup(mem)
                for line in mem.iterdump():
                    db_buf.write(f"{line}\n".encode("utf-8"))
                mem.close()
            finally:
                src.close()
            db_buf.seek(0)
            zf.writestr("chub.db.sql", db_buf.read())

    return buf.getvalue()


def save_backup(logger: Any = None) -> Path:
    """Write a timestamped backup into the backups directory; return its path."""
    data = build_backup_bytes()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = get_backup_dir(logger) / f"chub-backup-{timestamp}.zip"
    backup_path.write_bytes(data)
    if logger:
        logger.info(f"Backup created: {backup_path.name}")
    return backup_path

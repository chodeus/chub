"""Where CHUB keeps its config, database and logs. Resolve them here, nowhere else."""

import logging
import os
from pathlib import Path

# Stdlib-only on purpose: logger.py imports this, and helper.py imports logger.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_log = logging.getLogger(__name__)
_warned_legacy_db = False


def get_config_dir() -> str:
    """CONFIG_DIR if set, else /config in Docker, else <repo>/config."""
    configured = os.environ.get("CONFIG_DIR")
    if configured:
        return configured
    if os.environ.get("DOCKER_ENV"):
        return "/config"
    config_dir = _REPO_ROOT / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return str(config_dir)


def get_log_base_dir() -> str:
    """LOG_DIR if set, else <config dir>/logs in Docker, else <repo>/logs."""
    configured = os.environ.get("LOG_DIR")
    if configured:
        return configured
    if os.environ.get("DOCKER_ENV"):
        return os.path.join(get_config_dir(), "logs")
    return str(_REPO_ROOT / "logs")


def get_db_path() -> str:
    """chub.db in the config dir, unless it only exists in <repo>/config."""
    global _warned_legacy_db
    db_path = os.path.join(get_config_dir(), "chub.db")
    legacy = _REPO_ROOT / "config" / "chub.db"
    if (
        os.path.exists(db_path)
        or not legacy.is_file()
        or os.path.realpath(db_path) == os.path.realpath(legacy)
    ):
        return db_path
    if not _warned_legacy_db:
        _warned_legacy_db = True
        _log.warning(
            f"Using the database at {legacy}: CONFIG_DIR has none yet. "
            f"Stop CHUB and move chub.db (and any chub.db-wal / chub.db-shm) "
            f"to {db_path} to keep it with your config."
        )
    return str(legacy)

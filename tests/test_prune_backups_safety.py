"""Deletion safety for prune_old_backups.

backup_dir is user-configurable, so the prune loop deletes from a path the user
supplied. It must remove the directory entry itself, never follow a link, and —
given a config — re-confine the RESOLVED root before touching anything."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import backend.util.maintenance as maintenance
from backend.util.config import ChubConfig, ConfigParseError
from backend.util.maintenance import prune_old_backups

# Fixed mtimes so "oldest" is explicit rather than an artefact of creation order.
_BASE_MTIME = 1_700_000_000


class _Log:
    """Captures warning/error lines so a skip can be asserted as loud."""

    def __init__(self):
        """Start with empty capture lists."""
        self.warnings = []
        self.errors = []

    def info(self, *a, **k):
        """No-op."""

    def debug(self, *a, **k):
        """No-op."""

    def warning(self, msg, *a, **k):
        """Record a warning line."""
        self.warnings.append(str(msg))

    def error(self, msg, *a, **k):
        """Record an error line."""
        self.errors.append(str(msg))


def _archive(directory, name, age=0, body="zip"):
    """Write an archive whose mtime is `age` days before the base timestamp."""
    path = directory / name
    path.write_text(body)
    _age(path, age)
    return path


def _age(path, days):
    """Set `path`'s mtime to `days` before the base timestamp."""
    when = _BASE_MTIME - days * 86400
    os.utime(path, (when, when), follow_symlinks=False)


def test_prunes_oldest_and_keeps_newest(tmp_path):
    """Only the newest `keep` archives survive."""
    for i in range(5):
        _archive(tmp_path, f"chub-backup-2026080{i}-000000.zip", age=i)

    removed = prune_old_backups(tmp_path, keep=2)

    assert removed == 3
    survivors = {p.name for p in tmp_path.glob("chub-backup-*.zip")}
    assert survivors == {
        "chub-backup-20260800-000000.zip",
        "chub-backup-20260801-000000.zip",
    }


def test_a_symlinked_backup_never_unlinks_its_target(tmp_path):
    """The bug this guards: resolve()-then-unlink() deletes the TARGET."""
    backups = tmp_path / "backups"
    backups.mkdir()
    precious = tmp_path / "precious.zip"
    precious.write_text("must survive")
    # The sort key is f.stat().st_mtime, which FOLLOWS the link — so ageing the
    # target is what puts the link last and into the delete window.
    _age(precious, 2)

    _archive(backups, "chub-backup-20260803-000000.zip", age=0)
    _archive(backups, "chub-backup-20260802-000000.zip", age=1)
    link = backups / "chub-backup-20260801-000000.zip"
    link.symlink_to(precious)

    logger = _Log()
    prune_old_backups(backups, keep=2, logger=logger)

    assert precious.exists(), "prune followed the symlink and deleted its target"
    assert link.is_symlink(), "the link itself should be left alone, not resolved"
    assert any("non-regular" in w for w in logger.warnings)


def test_a_directory_named_like_a_backup_is_skipped(tmp_path):
    """A directory matching the archive glob is skipped, not rmtree'd."""
    _archive(tmp_path, "chub-backup-20260803-000000.zip", age=0)
    _archive(tmp_path, "chub-backup-20260802-000000.zip", age=1)
    stray = tmp_path / "chub-backup-20260801-000000.zip"
    stray.mkdir()
    _age(stray, 2)

    logger = _Log()
    removed = prune_old_backups(tmp_path, keep=2, logger=logger)

    assert removed == 0
    assert (tmp_path / "chub-backup-20260801-000000.zip").is_dir()


def test_keep_zero_or_negative_is_a_noop(tmp_path):
    """keep <= 0 disables pruning entirely."""
    _archive(tmp_path, "chub-backup-20260803-000000.zip")

    assert prune_old_backups(tmp_path, keep=0) == 0
    assert prune_old_backups(tmp_path, keep=-1) == 0
    assert len(list(tmp_path.glob("chub-backup-*.zip"))) == 1


def test_missing_directory_returns_zero(tmp_path):
    """A backup_dir that doesn't exist prunes nothing rather than raising."""
    assert prune_old_backups(tmp_path / "nope", keep=1) == 0


def test_unconfined_root_deletes_nothing(tmp_path):
    """A root that resolves outside the allowed roots must be refused, loudly."""
    for i in range(4):
        _archive(tmp_path, f"chub-backup-2026080{i}-000000.zip", age=i)
    logger = _Log()

    # A default ChubConfig's allowed roots are CONFIG_DIR + mounts, never tmp_path.
    removed = prune_old_backups(tmp_path, keep=1, logger=logger, config=ChubConfig())

    assert removed == 0
    assert len(list(tmp_path.glob("chub-backup-*.zip"))) == 4
    assert any("outside the allowed roots" in e for e in logger.errors)


def test_confined_root_still_prunes(tmp_path):
    """The re-confinement must not break the normal configured-root case."""
    backups = tmp_path / "backups"
    backups.mkdir()
    for i in range(4):
        _archive(backups, f"chub-backup-2026080{i}-000000.zip", age=i)

    config = ChubConfig()
    config.poster_renamerr.source_dirs = [str(tmp_path)]

    assert prune_old_backups(backups, keep=1, config=config) == 3
    assert len(list(backups.glob("chub-backup-*.zip"))) == 1


def test_auto_backup_hands_prune_a_config(monkeypatch, tmp_path):
    """The confinement is fail-open without a config — the caller must pass one."""
    captured = {}
    monkeypatch.setattr(maintenance, "save_backup", lambda logger=None: None)
    monkeypatch.setattr(maintenance, "get_backup_dir", lambda logger=None: tmp_path)
    monkeypatch.setattr(maintenance, "load_config", ChubConfig)
    monkeypatch.setattr(
        maintenance,
        "prune_old_backups",
        lambda d, k, lg=None, config=None: captured.update(config=config),
    )

    maintenance.run_auto_backup(3)
    assert isinstance(captured.get("config"), ChubConfig)


def test_auto_backup_failure_skips_the_cycle_without_killing_the_thread():
    """A config the backup path can't read logs and skips, never propagates."""
    logger = _Log()
    general = SimpleNamespace(
        auto_backup=True, auto_backup_keep=2, log_retention_days=0
    )

    with patch.object(maintenance, "save_backup", side_effect=ConfigParseError("bad")):
        maintenance._run_once(SimpleNamespace(general=general), logger)

    assert any("Auto-backup failed" in e for e in logger.errors)

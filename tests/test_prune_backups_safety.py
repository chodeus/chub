"""Deletion safety for prune_old_backups.

backup_dir is user-configurable, so the prune loop deletes from a path the user
supplied. It must remove the directory entry itself and never follow a link."""

import os

from backend.util.maintenance import prune_old_backups

# Fixed mtimes so "oldest" is explicit rather than an artefact of creation order.
_BASE_MTIME = 1_700_000_000


class _Log:
    def __init__(self):
        self.warnings = []

    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def warning(self, msg, *a, **k):
        self.warnings.append(str(msg))


def _archive(directory, name, age=0, body="zip"):
    """Write an archive whose mtime is `age` days before the base timestamp."""
    path = directory / name
    path.write_text(body)
    _age(path, age)
    return path


def _age(path, days):
    when = _BASE_MTIME - days * 86400
    os.utime(path, (when, when), follow_symlinks=False)


def test_prunes_oldest_and_keeps_newest(tmp_path):
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
    _archive(tmp_path, "chub-backup-20260803-000000.zip")

    assert prune_old_backups(tmp_path, keep=0) == 0
    assert len(list(tmp_path.glob("chub-backup-*.zip"))) == 1


def test_missing_directory_returns_zero(tmp_path):
    assert prune_old_backups(tmp_path / "nope", keep=1) == 0

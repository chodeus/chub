"""Tests for backend.util.backup.get_backup_dir — the configurable backup
location. A rejected or unusable backup_dir falls back to CONFIG_DIR/backups,
loudly; a config that won't LOAD denies instead — nothing validated the path."""

from datetime import datetime

import pytest

import backend.util.backup as backup_mod
from backend.util.config import ConfigParseError

_default_backup_dir = backup_mod._default_backup_dir
_get_backup_dir = backup_mod.get_backup_dir


class _Log:
    """Collects error lines so a fallback can be asserted as loud, not silent."""

    def __init__(self):
        self.errors = []

    def info(self, *a, **k):
        """No-op."""

    def error(self, msg, *a, **k):
        """Record an error line."""
        self.errors.append(str(msg))


class _Cfg:
    """Minimal stand-in exposing only general.backup_dir."""

    def __init__(self, backup_dir=""):
        self.general = type("G", (), {"backup_dir": backup_dir})()


class _FrozenClock:
    """datetime stand-in pinning now() so two saves share one timestamp."""

    @staticmethod
    def now():
        """Fixed instant."""
        return datetime(2026, 8, 11, 12, 0, 0)


def _stub_config(monkeypatch, backup_dir="", allowed=True):
    """Point backup_mod at a fake config with a fixed is_path_allowed verdict."""
    monkeypatch.setattr(backup_mod, "load_config", lambda: _Cfg(backup_dir))
    monkeypatch.setattr(backup_mod, "is_path_allowed", lambda p, c: allowed)


def test_defaults_to_config_dir_when_unset(monkeypatch, tmp_path):
    """No backup_dir configured: land in CONFIG_DIR/backups and create it."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    _stub_config(monkeypatch, backup_dir="")

    assert _get_backup_dir() == _default_backup_dir()
    assert (tmp_path / "backups").is_dir()


def test_uses_configured_dir_when_allowed(monkeypatch, tmp_path):
    """An allowed backup_dir is used verbatim and created."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "cfg"))
    target = tmp_path / "elsewhere" / "chub"
    _stub_config(monkeypatch, backup_dir=str(target), allowed=True)

    assert _get_backup_dir() == target
    assert target.is_dir()


def test_rejected_path_falls_back_and_logs(monkeypatch, tmp_path):
    """A backup_dir outside the allowed roots falls back and never gets made."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    outside = tmp_path / "not-allowed"
    _stub_config(monkeypatch, backup_dir=str(outside), allowed=False)
    logger = _Log()

    assert _get_backup_dir(logger) == _default_backup_dir()
    assert not outside.exists()
    assert any("outside the allowed roots" in e for e in logger.errors)


def test_unusable_path_falls_back_and_logs(monkeypatch, tmp_path):
    """An allowed-but-unmakeable backup_dir falls back loudly."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    # A file where the directory should be — mkdir raises OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    _stub_config(monkeypatch, backup_dir=str(blocker), allowed=True)
    logger = _Log()

    assert _get_backup_dir(logger) == _default_backup_dir()
    assert any("not usable" in e for e in logger.errors)


def test_unreadable_config_denies(monkeypatch, tmp_path):
    """Fail closed: an unloadable config validated no path, so write nowhere."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))

    def boom():
        """Stand-in load_config that fails."""
        raise ConfigParseError("config.yml is unparseable")

    monkeypatch.setattr(backup_mod, "load_config", boom)

    with pytest.raises(ConfigParseError):
        _get_backup_dir(_Log())
    assert not (tmp_path / "backups").exists()


def test_save_backup_never_overwrites_a_same_second_archive(monkeypatch, tmp_path):
    """Two backups in the same second must both survive, not truncate."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    _stub_config(monkeypatch, backup_dir="")
    monkeypatch.setattr(backup_mod, "build_backup_bytes", lambda: b"payload")
    # Frozen clock: the collision is the point, not a race the test might lose.
    monkeypatch.setattr(backup_mod, "datetime", _FrozenClock)

    first = backup_mod.save_backup()
    second = backup_mod.save_backup()

    assert first != second
    assert first.read_bytes() == second.read_bytes() == b"payload"
    assert len(list(_default_backup_dir().glob("chub-backup-*.zip"))) == 2

"""Tests for backend.api.system._get_backup_dir — the configurable backup
location. A backup landing in the wrong place beats one silently never written,
so every failure path must fall back to CONFIG_DIR/backups, loudly."""

import backend.api.system as system_mod

_default_backup_dir = system_mod._default_backup_dir
_get_backup_dir = system_mod._get_backup_dir


class _Log:
    def __init__(self):
        self.errors = []

    def info(self, *a, **k):
        pass

    def error(self, msg, *a, **k):
        self.errors.append(str(msg))


class _Cfg:
    def __init__(self, backup_dir=""):
        self.general = type("G", (), {"backup_dir": backup_dir})()


def _stub_config(monkeypatch, backup_dir="", allowed=True):
    monkeypatch.setattr(system_mod, "load_config", lambda: _Cfg(backup_dir))
    monkeypatch.setattr(system_mod, "is_path_allowed", lambda p, c: allowed)


def test_defaults_to_config_dir_when_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    _stub_config(monkeypatch, backup_dir="")

    assert _get_backup_dir() == _default_backup_dir()
    assert (tmp_path / "backups").is_dir()


def test_uses_configured_dir_when_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "cfg"))
    target = tmp_path / "elsewhere" / "chub"
    _stub_config(monkeypatch, backup_dir=str(target), allowed=True)

    assert _get_backup_dir() == target
    assert target.is_dir()


def test_rejected_path_falls_back_and_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    outside = tmp_path / "not-allowed"
    _stub_config(monkeypatch, backup_dir=str(outside), allowed=False)
    logger = _Log()

    assert _get_backup_dir(logger) == _default_backup_dir()
    assert not outside.exists()
    assert any("outside the allowed roots" in e for e in logger.errors)


def test_unusable_path_falls_back_and_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    # A file where the directory should be — mkdir raises OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    _stub_config(monkeypatch, backup_dir=str(blocker), allowed=True)
    logger = _Log()

    assert _get_backup_dir(logger) == _default_backup_dir()
    assert any("not usable" in e for e in logger.errors)


def test_unreadable_config_falls_back_and_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))

    def boom():
        raise RuntimeError("config.yml is unparseable")

    monkeypatch.setattr(system_mod, "load_config", boom)
    logger = _Log()

    assert _get_backup_dir(logger) == _default_backup_dir()
    assert any("Could not read backup_dir" in e for e in logger.errors)

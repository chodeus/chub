"""backend.util.paths: one answer for the config, database and log locations."""

import logging
import os

import pytest

import backend.util.paths as paths
from backend.util import backup
from backend.util.database import ChubDB


class _StubLogger:
    def get_adapter(self, *_a, **_kw):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: None


@pytest.fixture
def bare_metal(tmp_path, monkeypatch):
    """No container env; the repo root is a scratch folder."""
    for var in ("CONFIG_DIR", "LOG_DIR", "DOCKER_ENV"):
        monkeypatch.delenv(var, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(paths, "_REPO_ROOT", repo)
    monkeypatch.setattr(paths, "_warned_legacy_db", False)
    return repo


def test_bare_metal_defaults_to_the_repo(bare_metal):
    config_dir, log_dir, db_path = (
        paths.get_config_dir(),
        paths.get_log_base_dir(),
        paths.get_db_path(),
    )
    assert config_dir == str(bare_metal / "config")
    assert log_dir == str(bare_metal / "logs")
    assert db_path == str(bare_metal / "config" / "chub.db")


def test_bare_metal_honours_config_dir_for_the_database(
    bare_metal, tmp_path, monkeypatch
):
    conf = tmp_path / "conf"
    monkeypatch.setenv("CONFIG_DIR", str(conf))
    config_dir = paths.get_config_dir()
    db_path = ChubDB(logger=_StubLogger()).db_path
    backup_db, backup_dir = backup._get_db_path(), backup._default_backup_dir()
    assert config_dir == str(conf)
    assert db_path == str(conf / "chub.db")
    assert backup_db == str(conf / "chub.db")
    assert backup_dir == conf / "backups"


def test_docker_defaults(monkeypatch):
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    monkeypatch.delenv("LOG_DIR", raising=False)
    monkeypatch.setenv("DOCKER_ENV", "true")
    config_dir, log_dir = paths.get_config_dir(), paths.get_log_base_dir()
    assert config_dir == "/config"
    assert log_dir == "/config/logs"


def test_lone_legacy_database_is_used_with_one_warning(
    bare_metal, tmp_path, monkeypatch, caplog
):
    legacy = bare_metal / "config" / "chub.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "conf"))
    with caplog.at_level(logging.WARNING, logger="backend.util.paths"):
        db_path, backup_db = paths.get_db_path(), backup._get_db_path()
    assert db_path == str(legacy)
    assert backup_db == str(legacy)
    warnings = [r for r in caplog.records if "move chub.db" in r.getMessage()]
    assert len(warnings) == 1


def test_database_in_config_dir_wins_over_legacy(bare_metal, tmp_path, monkeypatch):
    legacy = bare_metal / "config" / "chub.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"")
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "chub.db").write_bytes(b"")
    monkeypatch.setenv("CONFIG_DIR", str(conf))
    db_path = paths.get_db_path()
    assert db_path == str(conf / "chub.db")


def test_logs_api_reads_where_the_logger_writes(bare_metal, tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import backend.api.logs as logs_api
    from backend.util.logger import Logger

    log_dir = tmp_path / "custom-logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    name = "poster_renamerr"
    log_file = log_dir / name / f"{name}.log"
    try:
        lg = Logger(log_level="INFO", module_name=name)
        lg._logger.info("written-for-the-logs-api")
        for h in lg._logger.handlers:
            h.flush()

        app = FastAPI()
        app.include_router(logs_api.router)
        app.dependency_overrides[logs_api.get_logger] = _StubLogger
        client = TestClient(app)
        listed = client.get(f"/api/logs/{name}")
        assert listed.status_code == 200, listed.text
        assert f"{name}.log" in listed.text
        body = client.get(f"/api/logs/{name}/{name}.log")
        assert "written-for-the-logs-api" in body.text
    finally:
        mod_logger = logging.getLogger(name)
        for h in list(mod_logger.handlers):
            h.close()
            mod_logger.removeHandler(h)
        Logger._initialized.discard((name, str(log_file)))
        assert not os.path.exists(bare_metal / "logs" / name)

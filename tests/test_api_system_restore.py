"""Tests for the /api/restore upload-size and zip-bomb guards.

The caps are monkeypatched down to a few KB so the rejection paths can be
exercised without building multi-hundred-MB payloads in memory. CONFIG_DIR is
pointed at a tmp dir so a restore that proceeds past the guards can never
touch the real config.
"""

import io
import zipfile

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import system as system_router  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Isolate get_config_path() and _get_backup_dir() from the real config.
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    app = FastAPI()
    app.state.logger = StubLogger()
    app.include_router(system_router.router)
    return TestClient(app)


def _zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _post_restore(client, payload):
    return client.post(
        "/api/restore",
        files={"file": ("backup.zip", payload, "application/zip")},
    )


def test_restore_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setattr(system_router, "MAX_RESTORE_UPLOAD_BYTES", 1024)
    resp = _post_restore(client, b"x" * 4096)
    assert resp.status_code == 413
    assert resp.json()["error_code"] == "BACKUP_TOO_LARGE"


def test_restore_rejects_zip_bomb_sql_member(client, monkeypatch):
    monkeypatch.setattr(system_router, "MAX_RESTORE_SQL_BYTES", 1024)
    # Highly compressible payload: tiny on the wire, over the cap inflated.
    payload = _zip_bytes({"config.yml": "a: 1\n", "chub.db.sql": b"\0" * 65536})
    resp = _post_restore(client, payload)
    assert resp.status_code == 413
    assert resp.json()["error_code"] == "BACKUP_MEMBER_TOO_LARGE"


def test_restore_rejects_oversized_config_member(client, monkeypatch):
    monkeypatch.setattr(system_router, "MAX_RESTORE_CONFIG_BYTES", 1024)
    payload = _zip_bytes({"config.yml": b"\0" * 65536})
    resp = _post_restore(client, payload)
    assert resp.status_code == 413
    assert resp.json()["error_code"] == "BACKUP_MEMBER_TOO_LARGE"


def test_restore_size_checks_pass_small_backup_through(client):
    """A normal-sized zip must clear both guards with the real caps in place:
    it reaches config validation (and fails there on a type-invalid config)
    rather than being size-rejected."""
    payload = _zip_bytes({"config.yml": "instances: 5\n"})
    resp = _post_restore(client, payload)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BACKUP_CONFIG"


def test_restore_rejects_non_zip(client):
    resp = _post_restore(client, b"definitely not a zip")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BACKUP"

"""Smoke tests for FastAPI API endpoints using TestClient.

Each test mounts an individual router on a fresh app to avoid the heavy
lifespan startup (database, workers) of the production app.
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import auth as auth_router  # noqa: E402
from backend.util.config import ChubConfig  # noqa: E402


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
def app_with_router():
    """Helper to build a fresh FastAPI app and attach state needed by handlers."""

    def _build(router):
        app = FastAPI()
        app.state.logger = StubLogger()
        app.state.db = None
        app.include_router(router)
        return app

    return _build


# --- Auth status endpoint (no auth required) ---


def test_auth_status_returns_unconfigured(monkeypatch, app_with_router, tmp_path):
    """A fresh install has no auth configured."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    # Override load_config in auth module so it picks up tmp env
    monkeypatch.setattr(
        "backend.api.auth.load_config", lambda: ChubConfig()
    )
    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["configured"] is False
    assert body["data"]["required"] is True


def test_auth_status_returns_configured(monkeypatch, app_with_router):
    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = "$2b$x"
    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)
    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.get("/api/auth/status")
    assert resp.json()["data"]["configured"] is True


# --- Logout (stateless) ---


def test_logout_endpoint(app_with_router):
    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# --- Setup (first-run) ---


def test_setup_creates_credentials(monkeypatch, app_with_router):
    config = ChubConfig()
    saved = []
    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)
    monkeypatch.setattr("backend.api.auth.save_config", lambda c: saved.append(c))

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/setup", json={"username": "admin", "password": "hunter2hunter"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    # save_config was invoked
    assert len(saved) == 1
    assert saved[0].auth.username == "admin"
    assert saved[0].auth.password_hash  # hashed, not empty
    assert saved[0].auth.password_hash != "hunter2hunter"
    assert saved[0].auth.jwt_secret  # generated


def test_setup_rejects_when_already_configured(monkeypatch, app_with_router):
    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = "$2b$x"
    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/setup", json={"username": "another", "password": "anotherpass"}
    )
    # Either 400 (bad request) or 403 (forbidden) — both mean "rejected"
    assert resp.status_code in (400, 403)
    assert resp.json()["success"] is False


# --- Login ---


def test_login_succeeds_with_correct_password(monkeypatch, app_with_router):
    from backend.util.auth import hash_password

    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("secret123")
    config.auth.jwt_secret = "test-secret-very-long-test-secret-very-long"

    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "secret123"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["token"]


def test_login_fails_with_wrong_password(monkeypatch, app_with_router):
    from backend.util.auth import hash_password

    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("secret123")
    config.auth.jwt_secret = "test-secret-very-long-test-secret-very-long"

    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code in (400, 401)
    assert resp.json()["success"] is False


def test_login_fails_with_unknown_user(monkeypatch, app_with_router):
    from backend.util.auth import hash_password

    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("secret123")
    config.auth.jwt_secret = "test-secret-very-long-test-secret-very-long"

    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "unknown", "password": "secret123"}
    )
    assert resp.status_code in (400, 401)

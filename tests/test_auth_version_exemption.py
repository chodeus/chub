"""AuthMiddleware: /api/version stays open, but its /check child needs a login."""

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import backend.api.main as apimain  # noqa: E402
from backend.util.auth import (  # noqa: E402
    create_access_token,
    generate_jwt_secret,
    hash_password,
)
from backend.util.config import ChubConfig  # noqa: E402


class _StubLogger:
    def get_adapter(self, *_a, **_kw):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: None


@pytest.fixture
def config(monkeypatch):
    cfg = ChubConfig()
    cfg.auth.username = "admin"
    cfg.auth.password_hash = hash_password("correct-horse-battery")
    cfg.auth.jwt_secret = generate_jwt_secret()
    monkeypatch.setattr(apimain, "load_config", lambda *a, **k: cfg)
    return cfg


@pytest.fixture
def client(config):
    app = FastAPI()
    app.state.logger = _StubLogger()
    app.add_middleware(apimain.AuthMiddleware)

    for path in ("/api/version", "/api/version/check", "/api/health"):
        app.add_api_route(path, lambda: {"ok": True}, methods=["GET"])
    return TestClient(app)


def test_version_is_open_without_a_login(client):
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_version_check_needs_a_login(client, config):
    assert client.get("/api/version/check").status_code == 401
    token = create_access_token("admin", config.auth.jwt_secret)
    resp = client.get(
        "/api/version/check", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200

"""POST /api/auth/disable: turning the login off, behind AuthMiddleware."""

import copy

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import backend.api.auth as auth_api  # noqa: E402
import backend.api.main as apimain  # noqa: E402
from backend.util.auth import (  # noqa: E402
    create_access_token,
    generate_jwt_secret,
    hash_password,
)
from backend.util.config import ChubConfig, ConfigError  # noqa: E402
from backend.util.rate_limiter import login_limiter  # noqa: E402

PASSWORD = "correct-horse-battery"


class _StubLogger:
    def get_adapter(self, *_a, **_kw):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Store:
    """load_config hands out copies and save_config replaces, like the real pair."""

    def __init__(self, config):
        self.config = config
        self.saves = 0

    def load(self):
        return copy.deepcopy(self.config)

    def save(self, config):
        self.saves += 1
        self.config = copy.deepcopy(config)


@pytest.fixture
def store(monkeypatch):
    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password(PASSWORD)
    config.auth.jwt_secret = generate_jwt_secret()
    s = _Store(config)
    monkeypatch.setattr(auth_api, "load_config", s.load)
    monkeypatch.setattr(auth_api, "save_config", s.save)
    monkeypatch.setattr(apimain, "load_config", s.load)
    with login_limiter._lock:
        login_limiter._buckets.clear()
    return s


@pytest.fixture
def client(store):
    app = FastAPI()
    app.state.logger = _StubLogger()
    app.add_middleware(apimain.AuthMiddleware)
    app.include_router(auth_api.router)
    app.dependency_overrides[auth_api.get_logger] = _StubLogger

    @app.get("/api/media/1")
    def protected():
        return {"ok": True}

    return TestClient(app)


def _bearer(store):
    token = create_access_token("admin", store.config.auth.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


def test_disable_clears_the_login_and_opens_the_api(client, store):
    assert client.get("/api/media/1").status_code == 401

    resp = client.post(
        "/api/auth/disable", json={"password": PASSWORD}, headers=_bearer(store)
    )

    assert resp.status_code == 200, resp.text
    assert store.config.auth.username == ""
    assert store.config.auth.password_hash == ""
    assert store.config.auth.jwt_secret == ""
    assert client.get("/api/media/1").status_code == 200
    status = client.get("/api/auth/status").json()["data"]
    assert status == {"configured": False, "required": False}


def test_disable_rejects_a_wrong_password_without_logging_the_user_out(client, store):
    resp = client.post(
        "/api/auth/disable", json={"password": "wrong-password"}, headers=_bearer(store)
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "AUTH_INVALID_PASSWORD"
    assert store.saves == 0
    assert store.config.auth.username == "admin"


def test_disable_needs_a_session_even_with_the_right_password(client, store):
    resp = client.post("/api/auth/disable", json={"password": PASSWORD})

    assert resp.status_code == 401
    assert resp.json()["error_code"] == "AUTH_REQUIRED"
    assert store.saves == 0


def test_disable_is_rate_limited(client, store):
    headers = _bearer(store)
    codes = [
        client.post(
            "/api/auth/disable", json={"password": "wrong-password"}, headers=headers
        ).status_code
        for _ in range(6)
    ]

    assert codes[:5] == [403] * 5
    assert codes[5] == 429
    assert store.saves == 0


def test_disable_when_the_login_is_already_off(client, store):
    store.config.auth.username = ""
    store.config.auth.password_hash = ""
    store.config.auth.jwt_secret = ""

    resp = client.post("/api/auth/disable", json={"password": PASSWORD})

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "AUTH_NOT_CONFIGURED"
    assert store.saves == 0


def test_disable_fails_closed_when_the_config_is_unreadable(client, store, monkeypatch):
    headers = _bearer(store)
    calls = {"n": 0}

    def flaky_load():
        # The middleware's read succeeds; the handler's read fails.
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConfigError("config.yml is unreadable")
        return store.load()

    monkeypatch.setattr(apimain, "load_config", flaky_load)
    monkeypatch.setattr(auth_api, "load_config", flaky_load)

    resp = client.post("/api/auth/disable", json={"password": PASSWORD}, headers=headers)

    assert resp.status_code == 500
    assert store.saves == 0
    assert store.config.auth.username == "admin"


def test_a_session_from_before_the_login_was_off_dies_with_it(client, store):
    old_headers = _bearer(store)
    disabled = client.post(
        "/api/auth/disable", json={"password": PASSWORD}, headers=old_headers
    )
    assert disabled.status_code == 200

    resp = client.post(
        "/api/auth/setup", json={"username": "admin", "password": "a-new-password"}
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/api/media/1", headers=old_headers).status_code == 401
    new_headers = {"Authorization": f"Bearer {resp.json()['data']['token']}"}
    assert client.get("/api/media/1", headers=new_headers).status_code == 200

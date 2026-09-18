"""The unauthenticated /api/auth/setup gate must deny when config can't be read.
Its only guard is _is_auth_configured, so a swallowed ConfigError meant "no account".
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth as auth_api
from backend.util.config import ConfigError


@pytest.fixture
def client():
    """Auth router on a bare app, with the production ConfigError handler."""
    from backend.api.main import handle_config_error

    app = FastAPI()
    # handle_config_error reads its logger off app.state, not through Depends.
    app.state.logger = _StubLogger()
    app.include_router(auth_api.router)
    app.add_exception_handler(ConfigError, handle_config_error)

    # Override, don't monkeypatch: Depends bound the original at import time.
    app.dependency_overrides[auth_api.get_logger] = _StubLogger
    return TestClient(app, raise_server_exceptions=False)


class _StubLogger:
    """No-op logger so the handlers can log without app.state."""

    def get_adapter(self, *_a, **_kw):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _break_config(monkeypatch):
    def boom(*_a, **_k):
        raise ConfigError("config.yml is unreadable")

    monkeypatch.setattr(auth_api, "load_config", boom)


def test_setup_denies_and_never_writes_when_config_is_unreadable(client, monkeypatch):
    """An unreadable config must not read as "no account configured"."""
    saved = []
    monkeypatch.setattr(auth_api, "save_config", lambda *a, **k: saved.append(a))
    _break_config(monkeypatch)

    resp = client.post(
        "/api/auth/setup", json={"username": "attacker", "password": "hunter2hunter2"}
    )

    assert resp.status_code != 200, "setup succeeded against an unreadable config"
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "CONFIG_INVALID"
    assert saved == [], "credentials were written despite the config read failing"


def test_auth_status_does_not_report_unconfigured_when_config_is_unreadable(
    client, monkeypatch
):
    """Reporting configured=false would send the UI into the setup wizard."""
    _break_config(monkeypatch)

    resp = client.get("/api/auth/status")

    assert resp.status_code == 500
    assert resp.json()["error_code"] == "CONFIG_INVALID"
    assert resp.json().get("data", {}).get("configured") is not False

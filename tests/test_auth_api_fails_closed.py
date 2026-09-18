"""The unauthenticated /api/auth/setup gate must deny when config can't be read.
Its only guard is _is_auth_configured, so a swallowed ConfigError meant "no account".
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth as auth_api
from backend.util.config import ConfigError


@pytest.fixture
def client(monkeypatch):
    """Auth router on a bare app, with the real ConfigError -> 503 handler."""
    app = FastAPI()
    app.include_router(auth_api.router)

    @app.exception_handler(ConfigError)
    async def _handler(request, exc):  # mirrors backend/api/main.py
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"success": False, "code": "CONFIG_INVALID", "message": str(exc)},
            status_code=503,
        )

    # Override, don't monkeypatch: Depends bound the original at import time.
    app.dependency_overrides[auth_api.get_logger] = _StubLogger
    return TestClient(app, raise_server_exceptions=False)


class _StubLogger:
    """No-op logger so the handlers can log without app.state."""

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
    assert resp.status_code == 503
    assert saved == [], "credentials were written despite the config read failing"


def test_auth_status_does_not_report_unconfigured_when_config_is_unreadable(
    client, monkeypatch
):
    """Reporting configured=false would send the UI into the setup wizard."""
    _break_config(monkeypatch)

    resp = client.get("/api/auth/status")

    assert resp.status_code == 503
    assert resp.json().get("data", {}).get("configured") is not False

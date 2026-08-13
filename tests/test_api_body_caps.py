"""Request-body cap wiring for every API module that reads a raw JSON body.

One representative route per swept module (backend/api/{config,modules,media_api,
posters,webhooks}.py): an oversized body must come back 413 BODY_TOO_LARGE from
backend.api.utils.read_request_json before the handler does any work — no config
write, no database touch. The guarded routes also keep refusing an absent body,
which the raw ``await request.json()`` used to do by raising.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import config as config_router  # noqa: E402
from backend.api import media_api as media_router  # noqa: E402
from backend.api import modules as modules_router  # noqa: E402
from backend.api import posters as posters_router  # noqa: E402
from backend.api import webhooks as webhooks_router  # noqa: E402
from backend.api.utils import MAX_REQUEST_BODY_BYTES  # noqa: E402
from backend.util.config import ChubConfig  # noqa: E402


class _StubLogger:
    """Swallows every log call and hands itself back as the adapter."""

    def debug(self, *a, **kw):
        """No-op."""

    def info(self, *a, **kw):
        """No-op."""

    def warning(self, *a, **kw):
        """No-op."""

    def error(self, *a, **kw):
        """No-op."""

    def get_adapter(self, *_a, **_kw):
        """Return self so adapter lookups keep working."""
        return self


class _TripwireDB:
    """Records any attribute touch — a touch means the body reached the handler."""

    def __init__(self):
        """Start with no touches recorded."""
        self.touched = []

    def __getattr__(self, name):
        """Record the access and honor the special-method contract."""
        self.touched.append(name)
        raise AttributeError(name)


# One raw-JSON-body route per swept module; each reads its body before any work.
_ROUTES = [
    pytest.param(config_router, "POST", "/api/config", id="config"),
    pytest.param(
        modules_router, "PUT", "/api/modules/poster_renamerr/config", id="module-config"
    ),
    pytest.param(
        modules_router, "PATCH", "/api/modules/poster_renamerr", id="module-toggle"
    ),
    pytest.param(media_router, "POST", "/api/media/collections", id="media"),
    pytest.param(posters_router, "POST", "/api/posters/collections", id="posters"),
    pytest.param(webhooks_router, "POST", "/api/webhooks/poster/add", id="webhook"),
    pytest.param(
        webhooks_router, "POST", "/api/webhooks/provision", id="webhook-provision"
    ),
]

# Routes that refuse an absent body; the raw parse used to raise into these.
_EMPTY_BODY_ROUTES = [
    pytest.param(
        config_router,
        "POST",
        "/api/config",
        400,
        "CONFIG_VALIDATION_ERROR",
        id="config",
    ),
    pytest.param(
        modules_router,
        "PUT",
        "/api/modules/poster_renamerr/config",
        400,
        "CONFIG_VALIDATION_ERROR",
        id="module-config",
    ),
    pytest.param(
        modules_router,
        "PATCH",
        "/api/modules/poster_renamerr",
        500,
        "MODULE_TOGGLE_ERROR",
        id="module-toggle",
    ),
    pytest.param(
        webhooks_router,
        "POST",
        "/api/webhooks/poster/add",
        500,
        "WEBHOOK_PROCESSING_ERROR",
        id="webhook",
    ),
]


@pytest.fixture
def make_client(monkeypatch):
    """Build (client, db, saves) for a router, with config writes disarmed."""
    saves = []

    def _record(cfg):
        """Capture the config instead of writing it to disk."""
        saves.append(cfg)

    # config.py binds save_config at import; modules.py imports it per call.
    monkeypatch.setattr(config_router, "save_config", _record)
    monkeypatch.setattr("backend.util.config.save_config", _record)
    monkeypatch.setattr(webhooks_router, "load_config", ChubConfig)

    def _make(module):
        """Mount one router on a fresh app with a stub logger and tripwire db."""
        app = FastAPI()
        app.state.logger = _StubLogger()
        db = _TripwireDB()
        app.state.db = db
        app.include_router(module.router)
        return TestClient(app, raise_server_exceptions=False), db, saves

    return _make


@pytest.mark.parametrize("module, method, path", _ROUTES)
def test_oversized_declared_body_is_refused(make_client, module, method, path):
    """A declared Content-Length past the cap is refused before any buffering."""
    client, db, saves = make_client(module)
    resp = client.request(
        method,
        path,
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413, resp.text
    assert resp.json()["error_code"] == "BODY_TOO_LARGE"
    assert db.touched == [], f"handler ran: db.{db.touched}"
    assert saves == []


@pytest.mark.parametrize("module, method, path", _ROUTES)
def test_oversized_chunked_body_is_refused(make_client, module, method, path):
    """Chunked sends no Content-Length, so the cap must also hold while streaming."""
    client, db, saves = make_client(module)
    chunk = b"x" * 64 * 1024
    body = (chunk for _ in range((MAX_REQUEST_BODY_BYTES // len(chunk)) + 2))
    resp = client.request(
        method, path, content=body, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 413, resp.text
    assert resp.json()["error_code"] == "BODY_TOO_LARGE"
    assert db.touched == [], f"handler ran: db.{db.touched}"
    assert saves == []


@pytest.mark.parametrize("module, method, path, status, code", _EMPTY_BODY_ROUTES)
def test_absent_body_is_still_refused(make_client, module, method, path, status, code):
    """The reader's {} for an absent body must not become a silent mutation."""
    client, db, saves = make_client(module)
    resp = client.request(method, path)
    assert resp.status_code == status, resp.text
    assert resp.json()["error_code"] == code
    assert db.touched == [], f"handler ran: db.{db.touched}"
    assert saves == []


def test_body_under_the_cap_still_reaches_the_handler(make_client):
    """The cap must not swallow a large-but-legal body — this one is a 400, not a 413."""
    client, _db, _saves = make_client(posters_router)
    resp = client.post(
        "/api/posters/collections",
        json={"padding": "x" * (MAX_REQUEST_BODY_BYTES // 2)},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "MISSING_NAME"

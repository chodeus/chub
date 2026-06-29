"""The instance edit flow must not clobber a stored API key with the redacted
placeholder. The frontend pre-fills the edit form with the redacted '********'
api, so an edit that doesn't retype the key sends '********' back — update must
resolve it against the stored key (same class of bug as the notification webhook
corruption). Create must reject the placeholder (no stored key to fall back on).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import instances as inst  # noqa: E402
from backend.util.config import (  # noqa: E402
    REDACTED_PLACEHOLDER,
    ChubConfig,
    InstanceDetail,
)


class _StubLog:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def get_adapter(self, *a, **k):
        return self


def _client():
    app = FastAPI()
    app.state.logger = _StubLog()
    app.state.db = None
    app.include_router(inst.router)
    return TestClient(app)


def test_update_instance_preserves_api_key_on_placeholder(monkeypatch):
    cfg = ChubConfig()
    cfg.instances.radarr["Main"] = InstanceDetail(
        url="http://r:7878", api="REAL-KEY-123"
    )
    saved = {}
    monkeypatch.setattr(inst, "load_config", lambda: cfg)
    monkeypatch.setattr(inst, "save_config", lambda c: saved.setdefault("cfg", c))
    monkeypatch.setattr(inst.plex_library_cache, "invalidate", lambda *a, **k: None)

    resp = _client().put(
        "/api/instances/Main",
        json={
            "service": "radarr",
            "name": "Main",
            "url": "http://r:7878",
            "api": REDACTED_PLACEHOLDER,  # edit without retyping the key
            "webhook_force_reupload": False,
        },
    )
    assert resp.status_code == 200, resp.text
    assert saved["cfg"].instances.radarr["Main"].api == "REAL-KEY-123"  # not '********'


def test_create_instance_rejects_placeholder_api(monkeypatch):
    monkeypatch.setattr(inst, "load_config", ChubConfig)
    monkeypatch.setattr(inst, "save_config", lambda c: None)
    monkeypatch.setattr(inst.plex_library_cache, "invalidate", lambda *a, **k: None)

    resp = _client().post(
        "/api/instances",
        json={
            "service": "radarr",
            "name": "New",
            "url": "http://r:7878",
            "api": REDACTED_PLACEHOLDER,
            "webhook_force_reupload": False,
        },
    )
    assert resp.status_code == 400

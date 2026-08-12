"""Request-shape contract for POST /api/cache/refresh.

A body that is valid JSON but not an object (e.g. ``[]``) used to reach
``payload.get`` and surface as a 500; it must be a 400 instead.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import cache as cache_router  # noqa: E402


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


class _StubWorker:
    """Records the payload each enqueue_job call receives."""

    def __init__(self):
        """Start with no captured jobs."""
        self.jobs = []

    def enqueue_job(self, _queue, payload, job_type=None):
        """Capture the job and report a fixed job id."""
        self.jobs.append((job_type, payload))
        return {"success": True, "data": {"job_id": 42}}


class _StubDB:
    """Minimal ChubDB stand-in exposing only the worker."""

    def __init__(self):
        """Attach a fresh recording worker."""
        self.worker = _StubWorker()


@pytest.fixture
def client_and_db():
    """Mount the cache router alone so no lifespan/database startup is needed."""
    app = FastAPI()
    app.state.logger = _StubLogger()
    db = _StubDB()
    app.state.db = db
    app.include_router(cache_router.router)
    return TestClient(app), db


def test_valid_body_enqueues_only_the_list_fields(client_and_db):
    """A well-formed body enqueues exactly the three list fields."""
    client, db = client_and_db
    resp = client.post(
        "/api/cache/refresh",
        json={"arr_instances": ["Radarr"], "plex_instances": [], "libraries": ["Movies"]},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["job_id"] == 42
    job_type, payload = db.worker.jobs[0]
    assert job_type == "cache_refresh"
    assert payload == {
        "arr_instances": ["Radarr"],
        "plex_instances": [],
        "libraries": ["Movies"],
    }


def test_empty_body_defaults_to_auto_discovery(client_and_db):
    """An empty object is valid: empty lists mean auto-discover everything."""
    client, db = client_and_db
    resp = client.post("/api/cache/refresh", json={})
    assert resp.status_code == 200
    assert db.worker.jobs[0][1] == {
        "arr_instances": [],
        "plex_instances": [],
        "libraries": [],
    }


@pytest.mark.parametrize("body", [[], "text", 3, True])
def test_non_object_body_is_rejected(client_and_db, body):
    """Valid JSON that is not an object must 400, not blow up as a 500."""
    client, db = client_and_db
    resp = client.post("/api/cache/refresh", json=body)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


@pytest.mark.parametrize("field", ["arr_instances", "plex_instances", "libraries"])
def test_non_list_field_is_rejected(client_and_db, field):
    """Each list field must actually be a list."""
    client, db = client_and_db
    resp = client.post("/api/cache/refresh", json={field: "Radarr"})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


def test_malformed_json_is_rejected(client_and_db):
    """An unparseable body is a client error, not a server error."""
    client, db = client_and_db
    resp = client.post(
        "/api/cache/refresh",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


@pytest.mark.parametrize("value", [True, False])
def test_update_mappings_is_no_longer_part_of_the_contract(client_and_db, value):
    """The dead flag is accepted but dropped — the worker always syncs mappings."""
    client, db = client_and_db
    resp = client.post("/api/cache/refresh", json={"update_mappings": value})
    assert resp.status_code == 200
    assert "update_mappings" not in db.worker.jobs[0][1]

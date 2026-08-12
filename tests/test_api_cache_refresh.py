"""Request-shape contract for the two routes that enqueue cache_refresh jobs.

POST /api/cache/refresh and POST /api/media/refresh share one validator
(backend.api.utils.build_cache_refresh_payload), so every body rule is asserted
against both. A body that is valid JSON but not an object (e.g. ``[]``) used to
reach ``payload.get`` — a 500 on the cache route, a silent all-instance refresh
on the media route.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import cache as cache_router  # noqa: E402
from backend.api import media_api as media_router  # noqa: E402


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


_ROUTERS = {"cache": cache_router.router, "media": media_router.router}


@pytest.fixture(params=sorted(_ROUTERS))
def refresh(request):
    """Yield (client, path, db) for each route sharing the cache_refresh contract."""
    app = FastAPI()
    app.state.logger = _StubLogger()
    db = _StubDB()
    app.state.db = db
    app.include_router(_ROUTERS[request.param])
    return TestClient(app), f"/api/{request.param}/refresh", db


def test_valid_body_enqueues_only_the_list_fields(refresh):
    """A well-formed body enqueues exactly the three list fields."""
    client, path, db = refresh
    resp = client.post(
        path,
        json={
            "arr_instances": ["Radarr"],
            "plex_instances": [],
            "libraries": ["Movies"],
        },
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


def test_empty_body_defaults_to_auto_discovery(refresh):
    """An empty object is valid: empty lists mean auto-discover everything."""
    client, path, db = refresh
    resp = client.post(path, json={})
    assert resp.status_code == 200
    assert db.worker.jobs[0][1] == {
        "arr_instances": [],
        "plex_instances": [],
        "libraries": [],
    }


def test_bodyless_post_is_a_full_refresh(refresh):
    """No body at all means no options — a full refresh, not a 400."""
    client, path, db = refresh
    resp = client.post(path)
    assert resp.status_code == 200
    assert db.worker.jobs[0][1] == {
        "arr_instances": [],
        "plex_instances": [],
        "libraries": [],
    }


@pytest.mark.parametrize("body", [b"", b"   \n"])
def test_empty_body_with_json_content_type_is_a_full_refresh(refresh, body):
    """An empty/whitespace body is "no content" even when declared as JSON."""
    client, path, db = refresh
    resp = client.post(
        path, content=body, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 200
    assert db.worker.jobs[0][1] == {
        "arr_instances": [],
        "plex_instances": [],
        "libraries": [],
    }


def test_frontend_format_still_enqueues_a_full_refresh(refresh):
    """The frontend's {path, deep} body carries no targeting keys, so it refreshes all."""
    client, path, db = refresh
    resp = client.post(path, json={"path": "/media/movies", "deep": True})
    assert resp.status_code == 200
    assert db.worker.jobs[0][1] == {
        "arr_instances": [],
        "plex_instances": [],
        "libraries": [],
    }


@pytest.mark.parametrize("body", [[], "text", 3, True])
def test_non_object_body_is_rejected(refresh, body):
    """Valid JSON that is not an object must 400, not blow up or refresh silently."""
    client, path, db = refresh
    resp = client.post(path, json=body)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


def test_json_null_body_is_rejected(refresh):
    """A literal JSON null parses fine but is not an object — still a 400."""
    client, path, db = refresh
    resp = client.post(
        path, content=b"null", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


@pytest.mark.parametrize("field", ["arr_instances", "plex_instances", "libraries"])
def test_non_list_field_is_rejected(refresh, field):
    """Each list field must actually be a list."""
    client, path, db = refresh
    resp = client.post(path, json={field: "Radarr"})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


def test_malformed_json_is_rejected(refresh):
    """An unparseable body is a client error, not a silent full refresh."""
    client, path, db = refresh
    resp = client.post(
        path, content=b"{not json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_BODY"
    assert db.worker.jobs == []


def test_charset_content_type_is_still_parsed(refresh):
    """A charset suffix must not bypass parsing into an unfiltered full refresh."""
    client, path, db = refresh
    resp = client.post(
        path,
        content=b'{"arr_instances": ["Radarr"]}',
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert resp.status_code == 200
    assert db.worker.jobs[0][1]["arr_instances"] == ["Radarr"]


@pytest.mark.parametrize("value", [True, False])
def test_update_mappings_is_dropped_but_siblings_survive(refresh, value):
    """The dead flag is stripped while real targeting keys pass through untouched."""
    client, path, db = refresh
    resp = client.post(
        path, json={"arr_instances": ["Radarr"], "update_mappings": value}
    )
    assert resp.status_code == 200
    payload = db.worker.jobs[0][1]
    assert payload["arr_instances"] == ["Radarr"]
    assert "update_mappings" not in payload

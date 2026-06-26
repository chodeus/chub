"""Tests for GET /api/jobs/webhook-origins — per-origin webhook telemetry
(client_host + count + last_seen + event_type) used by the Webhooks page."""

import os
import sys
import tempfile

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import jobs as jobs_router  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402


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
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(jobs_router.router)

    yield TestClient(app), db

    try:
        db.__exit__(None, None, None)
    finally:
        os.remove(path)


def _hit(db, host, event):
    db.worker.enqueue_job(
        "jobs",
        {
            "origin": {
                "client_host": host,
                "endpoint": "poster/add",
                "event_type": event,
            }
        },
        job_type="webhook",
    )


def test_webhook_origins_aggregates_with_last_seen(client):
    tc, db = client
    _hit(db, "10.0.0.5", "Download")
    _hit(db, "10.0.0.5", "Download")
    _hit(db, "10.0.0.2", "Test")

    res = tc.get("/api/jobs/webhook-origins?days=7")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] == 3

    by_origin = {r["client_host"]: r for r in data["by_origin"]}
    assert by_origin["10.0.0.5"]["count"] == 2
    assert by_origin["10.0.0.5"]["event_type"] == "Download"
    assert by_origin["10.0.0.5"]["last_seen"]  # populated, non-empty
    assert by_origin["10.0.0.2"]["count"] == 1


def test_webhook_origins_empty(client):
    tc, _db = client
    res = tc.get("/api/jobs/webhook-origins?days=7")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] == 0
    assert data["by_origin"] == []

"""Names are unique per service only, so a health check can name the service."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import instances as inst  # noqa: E402
from backend.util.config import ChubConfig, InstanceDetail  # noqa: E402
from tests.conftest import StubLogger  # noqa: E402


@pytest.fixture
def upstream(monkeypatch):
    # Only the outbound HTTP call is faked; each service's URL answers its own status.
    answers = {"http://10.0.0.1:32400": 200, "http://10.0.0.2:8989": 401}

    def fake_get(url, headers=None, **kwargs):
        base = next(b for b in answers if url.startswith(b))
        return MagicMock(ok=answers[base] < 400, status_code=answers[base], url=url)

    fake = MagicMock(side_effect=fake_get)
    monkeypatch.setattr(inst.requests, "get", fake)
    return fake


@pytest.fixture
def client():
    config = ChubConfig()
    config.instances.plex["main"] = InstanceDetail(url="http://10.0.0.1:32400", api="p")
    config.instances.sonarr["main"] = InstanceDetail(
        url="http://10.0.0.2:8989", api="s"
    )
    app = FastAPI()
    app.include_router(inst.router)
    app.dependency_overrides[inst.get_config] = lambda: config
    app.dependency_overrides[inst.get_logger] = lambda: StubLogger()
    return TestClient(app)


def _health(client, query=""):
    return client.get(f"/api/instances/main/health{query}")


def test_service_picks_the_same_named_instance(client, upstream):
    body = _health(client, "?service=sonarr").json()["data"]

    assert body["service"] == "sonarr"
    assert body["status"] == "unhealthy"
    assert upstream.call_args.args[0].startswith("http://10.0.0.2:8989")


def test_first_match_still_answers_without_a_service(client, upstream):
    assert _health(client).json()["data"]["service"] == "plex"


@pytest.mark.parametrize("service", ["radarr", "model_dump", "bogus"])
def test_a_service_without_that_name_is_not_found(client, upstream, service):
    response = _health(client, f"?service={service}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "INSTANCE_NOT_FOUND"
    upstream.assert_not_called()

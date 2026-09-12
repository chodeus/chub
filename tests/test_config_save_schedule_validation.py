"""Settings saves refuse a newly entered schedule that would never fire."""

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import config as config_router  # noqa: E402
from backend.api import modules as modules_router  # noqa: E402
from backend.util.config import ChubConfig  # noqa: E402
from backend.util.scheduler import new_invalid_schedule  # noqa: E402


class _Logger:
    """Absorbs every log call; get_adapter() hands back itself."""

    def __getattr__(self, _name):
        return lambda *a, **kw: self


def _config(**sections):
    return ChubConfig.model_validate(sections)


@pytest.fixture
def make_client(monkeypatch):
    """Mount one router over a stubbed config; returns (client, saves)."""

    def _make(router, base=None):
        base = base or _config()
        saves = []

        def load():
            return base.model_copy(deep=True)

        # config.py binds load/save at import; modules.py imports them per call.
        monkeypatch.setattr(config_router, "load_config", load)
        monkeypatch.setattr(config_router, "save_config", saves.append)
        monkeypatch.setattr("backend.util.config.load_config", load)
        monkeypatch.setattr("backend.util.config.save_config", saves.append)
        app = FastAPI()
        app.state.logger = _Logger()
        app.include_router(router.router)
        return TestClient(app, raise_server_exceptions=False), saves

    return _make


_BAD_MODULE_SAVES = [
    pytest.param(
        "upgradinatorr",
        {"instances_list": [{"instance": "sonarr", "schedule": "hourly(99)"}]},
        "upgradinatorr.instances_list[0].schedule",
        id="profile-hourly-99",
    ),
    pytest.param(
        "border_replacerr",
        {"holidays": [{"name": "xmas", "schedule": "daily(09:00)"}]},
        "border_replacerr.holidays[0].schedule",
        id="holiday-not-range",
    ),
    pytest.param(
        "border_replacerr",
        {"holidays": [{"name": "xmas", "schedule": "range(13/01-12/31)"}]},
        "border_replacerr.holidays[0].schedule",
        id="holiday-month-13",
    ),
]


@pytest.mark.parametrize("module, section, path", _BAD_MODULE_SAVES)
def test_module_save_refuses_bad_schedule(make_client, module, section, path):
    client, saves = make_client(modules_router)
    resp = client.put(f"/api/modules/{module}/config", json=section)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "INVALID_SCHEDULE"
    assert path in resp.text
    assert saves == []


@pytest.mark.parametrize(
    "module, section",
    [
        ("upgradinatorr", {"instances_list": [{"instance": "a", "schedule": "hourly(30)"}]}),
        ("upgradinatorr", {"instances_list": [{"instance": "a", "schedule": ""}]}),
        ("border_replacerr", {"holidays": [{"name": "x", "schedule": "range(12/01-12/31)"}]}),
    ],
)
def test_module_save_accepts_valid_schedule(make_client, module, section):
    client, saves = make_client(modules_router)
    resp = client.put(f"/api/modules/{module}/config", json=section)
    assert resp.status_code == 200, resp.text
    assert len(saves) == 1


@pytest.mark.parametrize(
    "body, path",
    [
        ({"schedule": {"nohl": "daily(25:00)"}}, "schedule.nohl"),
        (
            {"schedule_blocks": {"nohl": [{"label": "a", "schedule": "weekly(x@09:00)"}]}},
            "schedule_blocks.nohl[0].schedule",
        ),
    ],
)
def test_config_save_refuses_bad_schedule(make_client, body, path):
    client, saves = make_client(config_router)
    resp = client.post("/api/config", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "INVALID_SCHEDULE"
    assert path in resp.text
    assert saves == []


def test_existing_bad_schedule_does_not_block_unrelated_saves(make_client):
    base = _config(
        upgradinatorr={"instances_list": [{"instance": "a", "schedule": "hourly(99)"}]}
    )
    client, saves = make_client(modules_router, base)
    resp = client.put(
        "/api/modules/upgradinatorr/config",
        json={"instances_list": [{"instance": "a", "schedule": "hourly(99)", "count": 5}]},
    )
    assert resp.status_code == 200, resp.text

    client, saves = make_client(config_router, base)
    resp = client.post("/api/config", json={"schedule": {"nohl": "daily(03:00)"}})
    assert resp.status_code == 200, resp.text
    assert len(saves) == 1


def test_new_invalid_schedule_covers_every_schedule_field():
    old = _config()
    assert new_invalid_schedule(old, _config(schedule={"nohl": None})) is None
    assert new_invalid_schedule(old, _config(schedule={"nohl": 5})) == ("schedule.nohl", "5")
    assert new_invalid_schedule(
        old, _config(instances={"sync_schedule": "cron(not a cron)"})
    ) == ("instances.sync_schedule", "cron(not a cron)")

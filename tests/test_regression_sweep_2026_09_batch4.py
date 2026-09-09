"""Regression tests for the 2026-09 sweep, batch 4 — one per confirmed bug."""

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# get_logger's source was a client-controlled query parameter
# ---------------------------------------------------------------------------


def test_get_logger_takes_no_client_controlled_source():
    """`source` as a parameter makes it a query param on every Depends() route."""
    from backend.api.utils import get_logger

    assert list(inspect.signature(get_logger).parameters) == ["request"]


def test_notifications_reuses_the_shared_get_logger():
    """A second copy would keep the injectable parameter alive on its own routes."""
    import backend.api.notifications as notifications

    from backend.api.utils import get_logger

    assert notifications.get_logger is get_logger


def test_source_is_not_a_query_param_on_a_depends_route():
    from fastapi import Depends

    from backend.api.utils import get_logger

    app = FastAPI()

    @app.get("/probe")
    def probe(logger=Depends(get_logger)):  # noqa: ANN001
        return {"ok": True}

    params = app.openapi()["paths"]["/probe"]["get"].get("parameters", [])
    assert [p["name"] for p in params if p["in"] == "query"] == []


def test_forged_source_does_not_reach_the_log_adapter():
    """?source=<crlf> must not choose the adapter the line is written under."""
    from fastapi import Depends

    from backend.api.utils import get_logger

    seen = []

    class _Logger:
        def get_adapter(self, source):
            seen.append(source)
            return self

    app = FastAPI()
    app.state.logger = _Logger()

    @app.get("/probe")
    def probe(logger=Depends(get_logger)):  # noqa: ANN001
        return {"ok": True}

    client = TestClient(app)
    client.get("/probe", params={"source": "EVIL\nFORGED LINE"})
    assert seen == ["WEB"]


# ---------------------------------------------------------------------------
# PATCH /api/modules/{name} treated a missing `enabled` as "disable"
# ---------------------------------------------------------------------------


def _modules_client(monkeypatch, stored_schedule):
    """App with just the modules router, over an in-memory config."""
    import backend.api.modules as modules
    from backend.util.config import ChubConfig

    saved = {}

    def fake_load_config():
        cfg = ChubConfig()
        cfg.schedule = dict(stored_schedule)
        return cfg

    def fake_save_config(cfg):
        saved["schedule"] = dict(cfg.schedule or {})

    monkeypatch.setattr("backend.util.config.load_config", fake_load_config)
    monkeypatch.setattr("backend.util.config.save_config", fake_save_config)

    app = FastAPI()
    app.include_router(modules.router)  # router already carries prefix="/api"
    app.state.logger = type(
        "_L", (), {"get_adapter": lambda self, s: self, "debug": lambda self, *a: None,
                   "info": lambda self, *a: None, "warning": lambda self, *a: None,
                   "error": lambda self, *a, **k: None}
    )()
    return TestClient(app, raise_server_exceptions=False), saved


@pytest.mark.parametrize("body", [{"schedule": "0 5 * * *"}, {"unrelated": 1}])
def test_patch_without_enabled_is_rejected_and_keeps_the_schedule(monkeypatch, body):
    """A body with no `enabled` used to answer 200 and erase the stored cron."""
    client, saved = _modules_client(monkeypatch, {"border_replacerr": "0 3 * * *"})

    resp = client.patch("/api/modules/border_replacerr", json=body)

    assert resp.status_code == 400
    assert saved == {}  # nothing persisted, so the cron survives


def test_patch_with_non_boolean_enabled_is_rejected(monkeypatch):
    """`"false"` is truthy, so a string used to leave the module enabled."""
    client, saved = _modules_client(monkeypatch, {"border_replacerr": "0 3 * * *"})

    resp = client.patch("/api/modules/border_replacerr", json={"enabled": "false"})

    assert resp.status_code == 400
    assert saved == {}


# ---------------------------------------------------------------------------
# check_all_health keyed results by instance name, which collides across services
# ---------------------------------------------------------------------------


def test_same_name_in_two_services_does_not_overwrite(monkeypatch):
    """Names are unique per service, so "Main" existed twice and one vanished."""
    import backend.util.ssrf_guard as ssrf  # imported inside the route

    from backend.api.instances import check_all_health  # noqa: I001

    monkeypatch.setattr(ssrf, "is_safe_url", lambda url: (False, "refused"))

    cfg = type("C", (), {})()
    cfg.instances = type("I", (), {})()
    det = type("D", (), {"url": "http://x", "api": "k"})()
    cfg.instances.plex = {}
    cfg.instances.radarr = {"Main": det}
    cfg.instances.sonarr = {"Main": det}
    cfg.instances.lidarr = {}

    logger = type("L", (), {"debug": lambda *a: None, "error": lambda *a: None})()
    resp = check_all_health(config=cfg, logger=logger)

    import json

    health = json.loads(bytes(resp.body))["data"]["health"]
    assert set(health) == {"radarr:Main", "sonarr:Main"}


# ---------------------------------------------------------------------------
# An unreadable config reported "setup not completed" and trapped the install
# ---------------------------------------------------------------------------


def test_unreadable_config_is_not_reported_as_a_fresh_install(monkeypatch):
    """ConfigError means the file exists but is broken, so setup IS complete."""
    import backend.api.setup as setup
    from backend.util.config import ConfigError

    def boom(*a, **k):
        raise ConfigError("Invalid YAML syntax in config.yml at line 3, column 1")

    monkeypatch.setattr(setup, "load_config", boom)
    assert setup._is_setup_completed() is True


def test_missing_config_still_shows_the_wizard(monkeypatch):
    """The genuine first run must not be swallowed by the fix above."""
    import backend.api.setup as setup
    from backend.util.config import ChubConfig

    monkeypatch.setattr(setup, "load_config", lambda *a, **k: ChubConfig())
    assert setup._is_setup_completed() is False


# ---------------------------------------------------------------------------
# Both toggle endpoints share one validator, so both need coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [None, {}, {"other": 1}, {"enabled": "false"}])
def test_instance_toggle_rejects_a_missing_or_non_boolean_enabled(body):
    """Uncovered before the shared validator landed — a regression here was silent."""
    import json

    from backend.api.instances import toggle_instance

    logger = type("L", (), {"debug": lambda *a: None, "error": lambda *a: None})()
    resp = toggle_instance(instance_id="radarr:Main", body=body, logger=logger)

    assert resp.status_code == 400
    assert json.loads(bytes(resp.body))["error_code"] in (
        "MISSING_FIELD",
        "INVALID_FIELD",
    )

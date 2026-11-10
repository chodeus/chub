"""A save never gives two service types the same instance name; a config that already does still saves."""

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import config as config_router  # noqa: E402
from backend.api import instances as instances_router  # noqa: E402
from backend.util import config as cfg  # noqa: E402
from backend.util.instance_names import name_taken, new_shared_name  # noqa: E402

CLASH = "'Main' would name {} instances; each instance needs its own name, even across services"


class _Logger:
    def __getattr__(self, _name):
        return lambda *a, **kw: self


def _instances(**types):
    return cfg.InstancesConfig(
        **{
            kind: {n: cfg.InstanceDetail(url=f"http://{kind}-{n}", api="k") for n in names}
            for kind, names in types.items()
        }
    )


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """Seed a real config.yml; returns a reader for what is on disk now."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(instances_router.plex_library_cache, "invalidate", lambda *a, **k: None)

    def seed(**types):
        cfg.save_config(cfg.ChubConfig(instances=_instances(**types)))

    def names():
        inst = cfg.load_config().instances
        return {k: sorted(getattr(inst, k)) for k in ("radarr", "sonarr", "lidarr", "plex")}

    return seed, names


def _client():
    app = FastAPI()
    app.state.logger = _Logger()
    app.state.db = None
    app.include_router(instances_router.router)
    app.include_router(config_router.router)
    return TestClient(app, raise_server_exceptions=False)


def _body(**fields):
    return {"url": "http://new", "api": "k", "webhook_force_reupload": False, **fields}


def test_creating_an_instance_named_like_another_types_is_refused(saved):
    seed, names = saved
    seed(radarr=["Main"])

    resp = _client().post("/api/instances", json=_body(service="sonarr", name="Main"))

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INSTANCE_NAME_CONFLICT"
    assert resp.json()["message"] == CLASH.format("Radarr and Sonarr")
    assert names()["sonarr"] == []


def test_renaming_an_instance_to_another_types_name_is_refused(saved):
    seed, names = saved
    seed(radarr=["Main"], sonarr=["TV"])

    resp = _client().put("/api/instances/TV", json=_body(service="sonarr", name="Main"))

    assert resp.status_code == 400
    assert resp.json()["message"] == CLASH.format("Radarr and Sonarr")
    assert names()["sonarr"] == ["TV"]


def test_an_instance_with_its_own_name_still_creates(saved):
    seed, names = saved
    seed(radarr=["Main"])

    resp = _client().post("/api/instances", json=_body(service="sonarr", name="TV"))

    assert resp.status_code == 200, resp.text
    assert names()["sonarr"] == ["TV"]


def _settings_save(**types):
    instances = _instances(**types).model_dump(mode="python")
    return _client().post("/api/config", json={"instances": instances})


def test_a_settings_save_that_adds_a_shared_name_is_refused(saved):
    seed, names = saved
    seed(radarr=["Main"])

    resp = _settings_save(radarr=["Main"], plex=["Main"])

    assert resp.status_code == 400
    assert resp.json()["message"] == CLASH.format("Radarr and Plex")
    assert names()["plex"] == []


def test_a_config_that_already_shares_a_name_still_saves(saved):
    seed, names = saved
    seed(radarr=["Main"], sonarr=["Main"])

    resp = _settings_save(radarr=["Main"], sonarr=["Main"], lidarr=["Music"])

    assert resp.status_code == 200, resp.text
    assert names()["lidarr"] == ["Music"]


def test_an_existing_shared_name_cannot_spread_to_a_third_type(saved):
    seed, names = saved
    seed(radarr=["Main"], sonarr=["Main"])

    resp = _settings_save(radarr=["Main"], sonarr=["Main"], lidarr=["Main"])

    assert resp.status_code == 400
    assert resp.json()["message"] == CLASH.format("Radarr, Sonarr and Lidarr")
    assert names()["lidarr"] == []


def test_a_name_differing_only_in_case_is_the_same_name(saved):
    seed, names = saved
    seed(radarr=["Main"])

    resp = _client().post("/api/instances", json=_body(service="sonarr", name="main"))
    settings = _settings_save(radarr=["Main"], lidarr=["MAIN"])

    assert resp.json()["message"] == CLASH.format("Radarr and Sonarr").replace("'Main'", "'main'")
    assert settings.json()["message"] == CLASH.format("Radarr and Lidarr")
    assert (names()["sonarr"], names()["lidarr"]) == ([], [])


def test_the_rule_ignores_the_instances_own_type():
    instances = _instances(radarr=["Main"])

    assert name_taken(instances, "Main", "radarr") is None
    assert new_shared_name(instances, instances) is None

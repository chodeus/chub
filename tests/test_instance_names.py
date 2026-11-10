"""A save never gives two instances the same name, even across service types; a config that already does still saves."""

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import config as config_router  # noqa: E402
from backend.api import instances as instances_router  # noqa: E402
from backend.util import config as cfg  # noqa: E402
from backend.util.instance_names import name_taken, new_shared_name  # noqa: E402

TAIL = "; instance names must differ, ignoring case, even across services"


def _same(name, *others):
    named = " and ".join(f"{kind} instance '{n}'" for kind, n in others)
    return f"'{name}' is the same name as the {named}{TAIL}"


class _Logger:
    def __getattr__(self, _name):
        return lambda *a, **kw: self


def _instances(**types):
    return cfg.InstancesConfig(
        **{
            kind: {
                n: cfg.InstanceDetail(url=f"http://{kind}-{n}", api="k") for n in names
            }
            for kind, names in types.items()
        }
    )


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """Seed a real config.yml; returns a reader for what is on disk now."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        instances_router.plex_library_cache, "invalidate", lambda *a, **k: None
    )

    def seed(**types):
        cfg.save_config(cfg.ChubConfig(instances=_instances(**types)))

    def names():
        inst = cfg.load_config().instances
        return {
            k: sorted(getattr(inst, k)) for k in ("radarr", "sonarr", "lidarr", "plex")
        }

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


def _create(service, name):
    return _client().post("/api/instances", json=_body(service=service, name=name))


def _rename(service, old, new):
    return _client().put(f"/api/instances/{old}", json=_body(service=service, name=new))


def _settings_save(**types):
    instances = _instances(**types).model_dump(mode="python")
    return _client().post("/api/config", json={"instances": instances})


def _refused(resp, message):
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "INSTANCE_NAME_CONFLICT"
    assert resp.json()["message"] == message


@pytest.mark.parametrize(
    "service, name, kind",
    [
        ("sonarr", "Main", "sonarr"),
        ("sonarr", "main", "sonarr"),
        ("plex", " Main ", "plex"),
        ("radarr", "MAIN", "radarr"),
    ],
    ids=["other-type", "other-type-case", "other-type-spaces", "same-type-case"],
)
def test_creating_an_instance_with_a_taken_name_is_refused(saved, service, name, kind):
    seed, names = saved
    seed(radarr=["Main"])

    _refused(_create(service, name), _same(name, ("Radarr", "Main")))
    assert names()[kind] == (["Main"] if kind == "radarr" else [])


@pytest.mark.parametrize("service, name", [("sonarr", "TV"), ("sonarr", "Straße")])
def test_an_instance_with_its_own_name_still_creates(saved, service, name):
    seed, names = saved
    seed(radarr=["Main", "Strasse"])

    resp = _create(service, name)

    assert resp.status_code == 200, resp.text
    assert names()["sonarr"] == [name]


def test_renaming_an_instance_to_a_taken_name_is_refused(saved):
    seed, names = saved
    seed(radarr=["Main"], sonarr=["TV"])

    _refused(_rename("sonarr", "TV", "Main"), _same("Main", ("Radarr", "Main")))
    assert names()["sonarr"] == ["TV"]


def test_renaming_only_the_case_of_an_instances_own_name_is_allowed(saved):
    seed, names = saved
    seed(radarr=["Main"])

    resp = _rename("radarr", "Main", "MAIN")
    assert resp.status_code == 200
    assert names()["radarr"] == ["MAIN"]


def test_an_existing_clash_can_be_renamed_away_but_not_into_another_spelling(saved):
    seed, names = saved
    seed(radarr=["Main"], sonarr=["Main"])

    _refused(_rename("sonarr", "Main", "MAIN"), _same("MAIN", ("Radarr", "Main")))
    # A settings save merges into the saved instances, so the old spelling stays too.
    _refused(
        _settings_save(radarr=["Main"], sonarr=["MAIN"]),
        _same("MAIN", ("Radarr", "Main"), ("Sonarr", "Main")),
    )
    resp = _rename("sonarr", "Main", "TV")
    assert resp.status_code == 200
    assert names()["sonarr"] == ["TV"]


@pytest.mark.parametrize(
    "seeded, saving, message",
    [
        (
            {"radarr": ["Main"]},
            {"radarr": ["Main"], "plex": ["Main"]},
            _same("Main", ("Radarr", "Main")),
        ),
        (
            {"radarr": ["Main"]},
            {"radarr": ["Main"], "lidarr": ["MAIN"]},
            _same("MAIN", ("Radarr", "Main")),
        ),
        (
            {"radarr": ["Main"], "sonarr": ["Main"]},
            {"radarr": ["Main"], "sonarr": ["Main"], "lidarr": ["Main"]},
            _same("Main", ("Radarr", "Main"), ("Sonarr", "Main")),
        ),
    ],
    ids=["new-clash", "new-clash-other-case", "existing-clash-spreads"],
)
def test_a_settings_save_adding_a_taken_name_is_refused(saved, seeded, saving, message):
    seed, names = saved
    seed(**seeded)

    _refused(_settings_save(**saving), message)
    assert names() == {
        k: sorted(seeded.get(k, [])) for k in ("radarr", "sonarr", "lidarr", "plex")
    }


def test_a_config_that_already_shares_a_name_still_saves(saved):
    seed, names = saved
    seed(radarr=["Main"], sonarr=["Main"])

    resp = _settings_save(radarr=["Main"], sonarr=["Main"], lidarr=["Music"])

    assert resp.status_code == 200, resp.text
    assert names()["lidarr"] == ["Music"]


def test_the_rule_ignores_the_instance_itself():
    instances = _instances(radarr=["Main"])

    assert name_taken(instances, "Main", "radarr", current="Main") is None
    assert new_shared_name(instances, instances) is None

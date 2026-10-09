"""resync_media: re-sync exactly the named instances, and refuse anything it cannot re-sync."""

from types import SimpleNamespace

import pytest

from backend.util.config import ChubConfig, ConfigError, InstanceDetail
from backend.util.connector import resync_media


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


@pytest.fixture
def apps(monkeypatch):
    """Live config with radarr_main + plex_main; `apps.maps` records each sync, `apps.ok` its result."""
    cfg = ChubConfig()
    cfg.instances.radarr["radarr_main"] = InstanceDetail(url="http://radarr:7878", api="key")
    cfg.instances.plex["plex_main"] = InstanceDetail(url="http://plex:32400", api="token")
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    state = SimpleNamespace(cfg=cfg, maps=[], ok=True, broken=False)

    class _Connector:
        def __init__(self, db, logger, instance_map):
            if state.broken:
                raise RuntimeError("missing URL or API key")
            self.instance_map = instance_map
            state.maps.append(instance_map)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def update_arr_database(self):
            return [
                SimpleNamespace(instance_name=name, success=state.ok)
                for name in self.instance_map["arrs"]
            ]

        def update_collections_database(self):
            return [
                SimpleNamespace(instance_name=name, success=True)
                for name in self.instance_map["plex"]
            ]

    monkeypatch.setattr("backend.util.connector.Connector", _Connector)
    return state


def test_resyncs_arr_instances_and_plex_only_for_collections(apps):
    names = ["radarr_main", "plex_main"]

    with_collections = resync_media(None, _logger(), names, include_collections=True)
    without = resync_media(None, _logger(), names)

    assert (with_collections, without) == (True, True)
    assert apps.maps == [
        {"arrs": ["radarr_main"], "plex": {"plex_main": []}},
        {"arrs": ["radarr_main"], "plex": {}},
    ]


def test_nothing_to_resync_is_not_a_failure(apps):
    resynced = resync_media(None, _logger(), [])

    assert resynced is True
    assert apps.maps == []


@pytest.mark.parametrize(
    "names, disable",
    [
        (["radarr_main", "renamed_radarr"], None),
        (["not_configured"], None),
        (["radarr_main"], ("radarr", "radarr_main")),
        (["radarr_main", "plex_main"], ("plex", "plex_main")),
    ],
)
def test_refuses_a_name_it_cannot_resync(apps, names, disable):
    if disable:
        getattr(apps.cfg.instances, disable[0])[disable[1]].enabled = False

    resynced = resync_media(None, _logger(), names, include_collections=True)

    assert resynced is False
    assert apps.maps == []


def test_refuses_when_a_sync_fails_or_the_connector_cannot_start(apps):
    apps.ok = False
    failed_sync = resync_media(None, _logger(), ["radarr_main"])
    apps.ok, apps.broken = True, True
    broken = resync_media(None, _logger(), ["radarr_main"])

    assert (failed_sync, broken) == (False, False)


def test_refuses_when_the_config_cannot_load(apps, monkeypatch):
    def unreadable():
        raise ConfigError("unreadable config")

    monkeypatch.setattr("backend.util.config.load_config", unreadable)

    resynced = resync_media(None, _logger(), ["radarr_main"])

    assert resynced is False
    assert apps.maps == []

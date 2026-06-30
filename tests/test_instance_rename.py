"""Renaming an instance migrates its cached DB rows and rewrites the module
cross-references that point at it by name — and does NOT touch a same-named
instance of a different service.
"""

import os
import tempfile

import pytest

pytest.importorskip("httpx")


from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import instances as inst  # noqa: E402
from backend.api.instances import _rename_config_instance_refs  # noqa: E402
from backend.util.config import (  # noqa: E402
    REDACTED_PLACEHOLDER,
    ChubConfig,
    InstanceDetail,
    LabelarrMapping,
    LabelarrPlexInstance,
    NestarrMapping,
    NestarrPlexInstance,
    UpgradinatorrInstance,
)
from backend.util.database import ChubDB  # noqa: E402
from backend.util.normalization import normalize_titles  # noqa: E402
from tests.conftest import StubLogger  # noqa: E402


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    d.__enter__()
    d._ensure_schema_initialized()
    try:
        yield d
    finally:
        d.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            pass


def _item(title, **over):
    base = dict(
        title=title,
        normalized_title=normalize_titles(title),
        year=2026,
        alternate_titles=[],
        normalized_alternate_titles=[],
        monitored=True,
        has_content=False,
    )
    base.update(over)
    return base


def test_rename_migrates_only_matching_service(db):
    # Two services happen to share the instance name "main".
    db.media.upsert(_item("Movie A"), "movie", "radarr", "main")
    db.media.upsert(_item("Show A", season_number=None), "show", "sonarr", "main")
    db.sync_state.mark_synced("radarr", "main")
    db.sync_state.mark_synced("sonarr", "main")

    migrated = db.rename_instance("main", "Main", "radarr")
    assert migrated >= 2  # media_cache row + sync_state row

    rows = {
        (r["source"], r["instance_name"])
        for r in db.media.execute_query(
            "SELECT source, instance_name FROM media_cache", fetch_all=True
        )
    }
    assert ("radarr", "Main") in rows  # renamed
    assert ("sonarr", "main") in rows  # other service untouched

    scopes = {
        (r["scope"], r["instance_name"])
        for r in db.media.execute_query(
            "SELECT scope, instance_name FROM sync_state", fetch_all=True
        )
    }
    assert ("radarr", "Main") in scopes
    assert ("sonarr", "main") in scopes


def test_rename_noop_when_names_equal(db):
    db.media.upsert(_item("Movie A"), "movie", "radarr", "main")
    assert db.rename_instance("main", "main", "radarr") == 0


def test_config_refs_rewritten_for_arr_rename():
    cfg = ChubConfig()
    cfg.upgradinatorr.instances_list = [
        UpgradinatorrInstance(label="x", instance="main"),
        UpgradinatorrInstance(label="y", instance="other"),
    ]
    cfg.renameinatorr.instances = ["main", "other"]
    cfg.labelarr.mappings = [
        LabelarrMapping(
            app_instance="main",
            plex_instances=[LabelarrPlexInstance(instance="plex1")],
        )
    ]

    n = _rename_config_instance_refs(cfg, "main", "Main")

    assert cfg.upgradinatorr.instances_list[0].instance == "Main"
    assert cfg.upgradinatorr.instances_list[1].instance == "other"
    assert cfg.renameinatorr.instances == ["Main", "other"]
    assert cfg.labelarr.mappings[0].app_instance == "Main"
    # The plex ref inside the same mapping must be left alone.
    assert cfg.labelarr.mappings[0].plex_instances[0].instance == "plex1"
    assert n == 3  # upgradinatorr.instance + renameinatorr list + labelarr app_instance


def test_config_refs_rewritten_for_plex_rename():
    cfg = ChubConfig()
    cfg.nestarr.library_mappings = [
        NestarrMapping(
            arr_instance="sonarr1",
            plex_instances=[NestarrPlexInstance(instance="plex1")],
        )
    ]

    n = _rename_config_instance_refs(cfg, "plex1", "PlexMain")

    assert cfg.nestarr.library_mappings[0].plex_instances[0].instance == "PlexMain"
    assert cfg.nestarr.library_mappings[0].arr_instance == "sonarr1"  # untouched
    assert n == 1


def test_config_refs_leave_instances_mapping_alone():
    # The instances Dict on InstancesConfig must never be walked as a name list.
    cfg = ChubConfig()
    cfg.renameinatorr.instances = ["keepme"]
    n = _rename_config_instance_refs(cfg, "radarr", "Radarr")
    assert n == 0
    assert cfg.renameinatorr.instances == ["keepme"]


def test_rename_endpoint_end_to_end(db, monkeypatch):
    # Real PUT /api/instances/{id} through the route: config key rename +
    # cross-reference rewrite + cached-row migration, all together.
    cfg = ChubConfig()
    cfg.instances.sonarr["sonarr"] = InstanceDetail(url="http://s:8989", api="KEY")
    cfg.upgradinatorr.instances_list = [
        UpgradinatorrInstance(label="x", instance="sonarr")
    ]
    db.media.upsert(_item("Show A", season_number=None), "show", "sonarr", "sonarr")
    db.sync_state.mark_synced("sonarr", "sonarr")

    saved = {}
    monkeypatch.setattr(inst, "load_config", lambda: cfg)
    monkeypatch.setattr(inst, "save_config", lambda c: saved.setdefault("cfg", c))
    monkeypatch.setattr(inst.plex_library_cache, "invalidate", lambda *a, **k: None)

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(inst.router)

    resp = TestClient(app).put(
        "/api/instances/sonarr",
        json={
            "service": "sonarr",
            "name": "Sonarr",
            "url": "http://s:8989",
            "api": "KEY",
            "webhook_force_reupload": False,
        },
    )
    assert resp.status_code == 200, resp.text

    c = saved["cfg"]
    assert "Sonarr" in c.instances.sonarr
    assert "sonarr" not in c.instances.sonarr
    assert c.upgradinatorr.instances_list[0].instance == "Sonarr"

    rows = {
        (r["source"], r["instance_name"])
        for r in db.media.execute_query(
            "SELECT source, instance_name FROM media_cache", fetch_all=True
        )
    }
    assert ("sonarr", "Sonarr") in rows
    assert not any(name == "sonarr" for _, name in rows)


def test_test_endpoint_resolves_redacted_key_by_url_on_rename(monkeypatch):
    # Renaming sends the new name + the redacted key. The stored key must still
    # resolve (by URL, since the new name isn't in config yet) so the *arr isn't
    # tested with the literal placeholder and 401s ("Authentication required").
    cfg = ChubConfig()
    cfg.instances.sonarr["sonarr"] = InstanceDetail(url="http://s:8989", api="REALKEY")
    monkeypatch.setattr(inst, "load_config", lambda: cfg)
    monkeypatch.setattr("backend.util.ssrf_guard.is_safe_url", lambda u: (True, ""))

    captured = {}

    class _Resp:
        ok = True
        status_code = 200

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers or {}
        return _Resp()

    monkeypatch.setattr(inst.requests, "get", fake_get)

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = None
    app.include_router(inst.router)

    resp = TestClient(app).post(
        "/api/instances/test",
        json={
            "service": "sonarr",
            "name": "Sonarr",  # new name, not yet in config
            "url": "http://s:8989",
            "api": REDACTED_PLACEHOLDER,
        },
    )
    assert resp.status_code == 200, resp.text
    assert captured["headers"].get("X-Api-Key") == "REALKEY"

"""Tests for the global instance-level Plex library opt-in gate.

Covers the three moving parts of Stage A:
  - seed_plex_enabled_libraries: one-time None -> concrete-list backfill
  - Connector._determine_target_libraries: tri-state selection semantics
  - Connector._apply_instance_opt_in: the ingestion chokepoint (seed / opt-out /
    intersect)
  - the per-(instance, library) cache purge helpers
"""

import os
import tempfile

import pytest

from backend.util.config import (
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    load_config,
    save_config,
    seed_plex_enabled_libraries,
)
from backend.util import connector as connector_mod
from backend.util.connector import Connector
from backend.util.database import ChubDB


class _StubLogger:
    def __getattr__(self, _name):
        return lambda *a, **kw: None

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    handle = ChubDB(logger=_StubLogger(), db_path=path, quiet=True)
    handle.__enter__()
    handle._ensure_schema_initialized()
    try:
        yield handle
    finally:
        handle.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            # Best-effort temp cleanup; the file may already be gone.
            pass


def _make_connector(plex_detail: InstanceDetail) -> Connector:
    """Build a Connector with an empty instance_map, then override its config
    snapshot so _apply_instance_opt_in reads exactly the instance we crafted."""
    c = Connector(instance_map={})
    c.config = ChubConfig(instances=InstancesConfig(plex={"plex_main": plex_detail}))
    return c


# --- seed_plex_enabled_libraries (pure, tmp-path persistence) ---


def test_seed_backfills_none(tmp_path):
    cfg_path = os.path.join(tmp_path, "config.yml")
    cfg = ChubConfig(
        instances=InstancesConfig(
            plex={"plex_main": InstanceDetail(url="http://p", api="t")}
        )
    )
    save_config(cfg, cfg_path)

    seeded = seed_plex_enabled_libraries(
        "plex_main", ["Movies", "TV", "Movies"], path=cfg_path
    )
    assert seeded is True

    reloaded = load_config(cfg_path)
    # De-duped, order preserved.
    assert reloaded.instances.plex["plex_main"].enabled_libraries == ["Movies", "TV"]


def test_seed_is_noop_when_already_set(tmp_path):
    cfg_path = os.path.join(tmp_path, "config.yml")
    cfg = ChubConfig(
        instances=InstancesConfig(
            plex={
                "plex_main": InstanceDetail(
                    url="http://p", api="t", enabled_libraries=["Movies"]
                )
            }
        )
    )
    save_config(cfg, cfg_path)

    seeded = seed_plex_enabled_libraries("plex_main", ["Movies", "TV"], path=cfg_path)
    assert seeded is False
    assert load_config(cfg_path).instances.plex["plex_main"].enabled_libraries == [
        "Movies"
    ]


def test_seed_empty_list_is_not_reseeded(tmp_path):
    """An explicit opt-out ([]) must NOT be treated as unset and re-seeded."""
    cfg_path = os.path.join(tmp_path, "config.yml")
    cfg = ChubConfig(
        instances=InstancesConfig(
            plex={
                "plex_main": InstanceDetail(
                    url="http://p", api="t", enabled_libraries=[]
                )
            }
        )
    )
    save_config(cfg, cfg_path)

    seeded = seed_plex_enabled_libraries("plex_main", ["Movies"], path=cfg_path)
    assert seeded is False
    assert load_config(cfg_path).instances.plex["plex_main"].enabled_libraries == []


# --- _determine_target_libraries (tri-state) ---


def test_determine_none_selection_returns_all():
    c = _make_connector(InstanceDetail(url="http://p", api="t"))
    assert c._determine_target_libraries(["Movies", "TV"], None) == ["Movies", "TV"]


def test_determine_empty_selection_returns_all():
    # Empty per-caller scope == all (of whatever was passed in, already gated).
    c = _make_connector(InstanceDetail(url="http://p", api="t"))
    assert c._determine_target_libraries(["Movies", "TV"], []) == ["Movies", "TV"]


def test_determine_list_intersects_case_insensitively():
    c = _make_connector(InstanceDetail(url="http://p", api="t"))
    assert c._determine_target_libraries(
        ["Movies", "TV", "Anime"], ["movies", "anime"]
    ) == [
        "Movies",
        "Anime",
    ]


# --- _apply_instance_opt_in (the chokepoint) ---


def test_apply_opt_in_seeds_when_none(monkeypatch):
    calls = {}

    def fake_seed(name, libs, path=None):
        calls["name"] = name
        calls["libs"] = list(libs)
        return True

    monkeypatch.setattr(connector_mod, "seed_plex_enabled_libraries", fake_seed)

    c = _make_connector(
        InstanceDetail(url="http://p", api="t")
    )  # enabled_libraries=None
    allowed = c._apply_instance_opt_in("plex_main", ["Movies", "TV"])
    # Legacy/unset -> all libraries pass through (nothing silently hidden)...
    assert allowed == ["Movies", "TV"]
    # ...and the allow-list is seeded so libraries added LATER stay hidden.
    assert calls == {"name": "plex_main", "libs": ["Movies", "TV"]}
    # In-memory snapshot updated so the collections pass doesn't re-seed.
    assert c.config.instances.plex["plex_main"].enabled_libraries == ["Movies", "TV"]


def test_apply_opt_in_empty_list_blocks_everything(monkeypatch):
    monkeypatch.setattr(
        connector_mod,
        "seed_plex_enabled_libraries",
        lambda *a, **k: pytest.fail("must not seed an opted-out instance"),
    )
    c = _make_connector(InstanceDetail(url="http://p", api="t", enabled_libraries=[]))
    assert c._apply_instance_opt_in("plex_main", ["Movies", "TV"]) == []


def test_apply_opt_in_list_intersects(monkeypatch):
    monkeypatch.setattr(
        connector_mod,
        "seed_plex_enabled_libraries",
        lambda *a, **k: pytest.fail("must not seed an already-configured instance"),
    )
    c = _make_connector(
        InstanceDetail(url="http://p", api="t", enabled_libraries=["Movies"])
    )
    # A library present in Plex but not opted in is dropped; an opted-in library
    # no longer present in Plex simply doesn't appear.
    assert c._apply_instance_opt_in("plex_main", ["Movies", "TV"]) == ["Movies"]
    assert c._apply_instance_opt_in("plex_main", ["TV"]) == []


def test_apply_opt_in_unknown_instance_fails_closed(monkeypatch):
    monkeypatch.setattr(
        connector_mod,
        "seed_plex_enabled_libraries",
        lambda *a, **k: pytest.fail("an unknown instance must not be seeded"),
    )
    c = _make_connector(InstanceDetail(url="http://p", api="t"))
    # An instance absent from config -> fail closed, no seed.
    assert c._apply_instance_opt_in("does_not_exist", ["Movies", "TV"]) == []


# --- per-(instance, library) cache purge helpers (opt-out) ---


def _insert_plex_row(db, instance, library, plex_id):
    db.plex.execute_query(
        "INSERT INTO plex_media_cache (plex_id, instance_name, library_name, title) "
        "VALUES (?, ?, ?, ?)",
        (plex_id, instance, library, f"t{plex_id}"),
    )


def test_plex_cache_clear_library_purges_only_that_library(db):
    _insert_plex_row(db, "plex_main", "Movies", "1")
    _insert_plex_row(db, "plex_main", "TV", "2")
    _insert_plex_row(db, "plex_main", "TV", "3")
    _insert_plex_row(db, "other", "TV", "4")

    assert set(db.plex.get_library_names_for_instance("plex_main")) == {"Movies", "TV"}

    deleted = db.plex.clear_library("plex_main", "TV")
    assert deleted == 2
    # Movies for this instance and TV for the other instance are untouched.
    assert db.plex.get_library_names_for_instance("plex_main") == ["Movies"]
    assert db.plex.get_library_names_for_instance("other") == ["TV"]


# --- PATCH /api/plex/{instance}/libraries (endpoint integration) ---


def test_patch_libraries_sets_prunes_and_purges(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api import instances as inst_mod
    from backend.api.instances import get_config, router
    from backend.util.config import PlexScope

    cfg = ChubConfig(
        instances=InstancesConfig(
            plex={"plex_main": InstanceDetail(url="u", api="k")}  # None -> unset
        )
    )
    cfg.poster_renamerr.plex_scope = [
        PlexScope(instance="plex_main", library_names=["Movies", "TV"])
    ]

    saved = {}
    monkeypatch.setattr(inst_mod, "save_config", lambda c, *a, **k: saved.update(c=c))
    monkeypatch.setattr(inst_mod.plex_library_cache, "invalidate", lambda *a, **k: None)

    class _StubCache:
        def __init__(self, libs):
            self._libs = libs

        def get_library_names_for_instance(self, _n):
            return list(self._libs)

        def clear_library(self, _n, _lib):
            return 1

    class _StubDB:
        plex = _StubCache(["Movies", "TV"])
        collection = _StubCache([])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(inst_mod, "ChubDB", lambda *a, **k: _StubDB())

    app = FastAPI()
    app.state.logger = _StubLogger()
    app.state.db = None
    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: cfg

    client = TestClient(app)
    resp = client.patch(
        "/api/plex/plex_main/libraries", json={"enabled_libraries": ["Movies"]}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["enabled_libraries"] == ["Movies"]
    assert data["pruned_module_refs"] == 1  # "TV" pruned from plex_scope
    assert data["purged_rows"] == 1  # "TV" cache rows purged

    # Config actually mutated + saved.
    assert cfg.instances.plex["plex_main"].enabled_libraries == ["Movies"]
    assert cfg.poster_renamerr.plex_scope[0].library_names == ["Movies"]
    assert saved["c"] is cfg


def test_update_instance_preserves_optin_and_enabled(monkeypatch):
    """Editing an instance's URL/key must NOT wipe the enabled toggle or the
    Plex library opt-in (owned by separate endpoints, not the edit form)."""
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api import instances as inst_mod
    from backend.api.instances import router

    cfg = ChubConfig(
        instances=InstancesConfig(
            plex={
                "plex_main": InstanceDetail(
                    url="http://old",
                    api="k",
                    enabled=False,
                    enabled_libraries=["Movies"],
                )
            }
        )
    )
    saved = {}
    monkeypatch.setattr(inst_mod, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(inst_mod, "save_config", lambda c, *a, **k: saved.update(c=c))
    monkeypatch.setattr(inst_mod.plex_library_cache, "invalidate", lambda *a, **k: None)

    app = FastAPI()
    app.state.logger = _StubLogger()
    app.state.db = None
    app.include_router(router)

    client = TestClient(app)
    resp = client.put(
        "/api/instances/plex_main",
        json={
            "service": "plex",
            "name": "plex_main",
            "url": "http://new",
            "api": "k",
        },
    )
    assert resp.status_code == 200
    detail = cfg.instances.plex["plex_main"]
    assert detail.url == "http://new"  # the edit applied
    assert detail.enabled is False  # ...but the toggle survived
    assert detail.enabled_libraries == ["Movies"]  # ...and so did the opt-in


def test_patch_libraries_unknown_instance_404(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.instances import get_config, router

    cfg = ChubConfig()
    app = FastAPI()
    app.state.logger = _StubLogger()
    app.state.db = None
    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: cfg

    client = TestClient(app)
    resp = client.patch("/api/plex/nope/libraries", json={"enabled_libraries": []})
    assert resp.status_code == 404

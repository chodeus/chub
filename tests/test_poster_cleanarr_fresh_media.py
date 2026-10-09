"""Poster Cleanarr re-syncs the media it compares against before deciding what to delete."""

from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import (
    PosterCleanarr,
    delete_orphan_asset,
    invalidate_kometa_assets_cache,
    scan_kometa_assets,
)
from backend.util.config import ChubConfig, ConfigError, InstanceDetail
from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
        log_outro=lambda *a, **k: None,
    )


def _seed(db, key, title, tmdb=None, folder=None):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, folder, asset_type) VALUES (?, 'radarr_main', ?, ?, ?, 'movie')",
        (key, normalize_titles(title), tmdb, folder),
    )


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Real DB + asset dir; `env.sync(db)` is what Radarr holds now, `env.ok` the sync result."""
    invalidate_kometa_assets_cache()
    assets = tmp_path / "assets"
    assets.mkdir()
    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(tmp_path)]
    cfg.instances.radarr["radarr_main"] = InstanceDetail(
        url="http://radarr:7878", api="key"
    )
    cfg.poster_cleanarr.asset_dirs = [str(assets)]
    cfg.poster_cleanarr.orphan_instances = ["radarr_main"]
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    state = SimpleNamespace(
        cfg=cfg, assets=assets, maps=[], ok=True, broken=False, sync=lambda db: None
    )

    class _Connector:
        def __init__(self, db, logger, instance_map):
            if state.broken:
                raise RuntimeError("ARR instance 'radarr_main' missing URL or API key")
            self.db = db
            state.maps.append(instance_map)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def update_arr_database(self):
            if state.ok:
                state.sync(self.db)
            return [SimpleNamespace(instance_name="radarr_main", success=state.ok)]

        def update_collections_database(self):
            return []

    monkeypatch.setattr("backend.modules.poster_cleanarr.Connector", _Connector)

    class _SameDB:
        """run() opens its own ChubDB; hand it the test DB, never the default config/chub.db."""

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return state.db

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("backend.modules.poster_cleanarr.ChubDB", _SameDB)
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db"), quiet=True) as db:
        _seed(db, "k1", "Keeper (2020)")
        state.db = db
        yield state
    invalidate_kometa_assets_cache()


def _asset(env, name):
    path = env.assets / name
    path.write_bytes(b"x")
    return path


def _new_title_added(db):
    _seed(db, "k2", "New Movie (2024)")


def test_delete_spares_an_asset_whose_title_was_added_since_the_last_sync(env):
    new = _asset(env, "New Movie (2024).jpg")
    env.sync = _new_title_added

    outcome, _ = delete_orphan_asset(env.db, str(new), env.cfg, _logger())

    assert outcome == "not_orphan"
    assert new.exists()
    assert env.maps == [{"arrs": ["radarr_main"], "plex": {}}]


def test_delete_refuses_when_the_refresh_fails(env):
    gone = _asset(env, "Gone Movie (2019).jpg")
    env.ok = False

    outcome, orphans = delete_orphan_asset(env.db, str(gone), env.cfg, _logger())

    assert (outcome, orphans) == ("unavailable", None)
    assert gone.exists()


def test_delete_refuses_when_the_connector_cannot_start(env):
    gone = _asset(env, "Gone Movie (2019).jpg")
    env.broken = True

    outcome, _ = delete_orphan_asset(env.db, str(gone), env.cfg, _logger())

    assert outcome == "unavailable"
    assert gone.exists()


def test_scan_lists_only_true_orphans_after_the_refresh(env):
    gone = _asset(env, "Gone Movie (2019).jpg")
    _asset(env, "New Movie (2024).jpg")
    env.sync = _new_title_added

    result = scan_kometa_assets(env.db, _logger(), force=True)

    assert [o["path"] for o in result["orphans"]] == [str(gone)]


def test_scan_fails_when_the_refresh_fails(env):
    _asset(env, "Gone Movie (2019).jpg")
    env.ok = False

    with pytest.raises(RuntimeError):
        scan_kometa_assets(env.db, _logger(), force=True)


def _module(env, **flags):
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
    # Snapshot from before radarr_main was configured: the run must use the live config
    m.full_config = ChubConfig()
    m.config = env.cfg.poster_cleanarr
    for key, value in flags.items():
        setattr(m.config, key, value)
    return m


def test_run_removes_only_true_orphans_after_the_refresh(env):
    gone = _asset(env, "Gone Movie (2019).jpg")
    new = _asset(env, "New Movie (2024).jpg")
    env.sync = _new_title_added
    m = _module(env, orphan_assets_enabled=True, orphan_assets_mode="remove")

    orphan_stats, _ = m._run_asset_passes()

    assert orphan_stats["count"] == 1
    assert not gone.exists()
    assert new.exists()


def test_run_skips_both_passes_when_the_refresh_fails(env):
    gone = _asset(env, "Gone Movie (2019).jpg")
    env.ok = False
    m = _module(
        env,
        orphan_assets_enabled=True,
        orphan_assets_mode="remove",
        stale_duplicates_enabled=True,
        stale_duplicates_mode="remove",
    )

    orphan_stats, stale_stats = m._run_asset_passes()

    assert (orphan_stats["count"], stale_stats["count"]) == (0, 0)
    assert gone.exists()


def test_run_skips_both_passes_when_the_live_config_cannot_load(env, monkeypatch):
    gone = _asset(env, "Gone Movie (2019).jpg")

    def broken():
        raise ConfigError("unreadable config")

    monkeypatch.setattr("backend.util.config.load_config", broken)
    m = _module(env, orphan_assets_enabled=True, orphan_assets_mode="remove")

    orphan_stats, _ = m._run_asset_passes()

    assert orphan_stats["count"] == 0
    assert gone.exists()
    assert env.maps == []


def test_stale_pass_uses_the_folder_name_radarr_has_now(env):
    _seed(env.db, "k3", "Some Film (2024)", tmdb=500, folder="Old Name (2024) {tmdb-500}")
    (env.assets / "New Name (2024) {tmdb-500}").mkdir()

    def renamed(db):
        db.media.execute_query(
            "UPDATE media_cache SET folder = ? WHERE identity_key = 'k3'",
            ("New Name (2024) {tmdb-500}",),
        )

    env.sync = renamed
    m = _module(env, stale_duplicates_enabled=True, stale_duplicates_mode="report")

    _, stale_stats = m._run_asset_passes()

    assert stale_stats["count"] == 0


def test_refresh_scope_is_arr_instances_plus_plex_for_collections(env):
    env.cfg.instances.plex["plex_main"] = InstanceDetail(
        url="http://plex:32400", api="token"
    )
    names = ["radarr_main", "plex_main"]

    with_collections = PosterCleanarr._refresh_comparison_set(
        env.db, names, True, env.cfg, _logger()
    )
    without = PosterCleanarr._refresh_comparison_set(
        env.db, names, False, env.cfg, _logger()
    )

    assert (with_collections, without) == (True, True)
    assert env.maps == [
        {"arrs": ["radarr_main"], "plex": {"plex_main": []}},
        {"arrs": ["radarr_main"], "plex": {}},
    ]


@pytest.mark.parametrize(
    "names, disabled",
    [
        (["radarr_main", "renamed_radarr"], None),
        (["not_configured"], None),
        (["radarr_main"], "radarr_main"),
        (["radarr_main", "plex_main"], "plex_main"),
    ],
)
def test_refresh_refuses_a_selection_it_cannot_resync(env, names, disabled):
    env.cfg.instances.plex["plex_main"] = InstanceDetail(
        url="http://plex:32400", api="token"
    )
    if disabled == "radarr_main":
        env.cfg.instances.radarr["radarr_main"].enabled = False
    elif disabled:
        env.cfg.instances.plex[disabled].enabled = False

    refreshed = PosterCleanarr._refresh_comparison_set(
        env.db, names, True, env.cfg, _logger()
    )

    assert refreshed is False
    assert env.maps == []

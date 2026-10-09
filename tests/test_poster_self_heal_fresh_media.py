"""Poster Self-Heal matches posters against media re-synced at run time, never a stale cache."""

from types import SimpleNamespace

import pytest

from backend.modules.poster_self_heal import PosterSelfHeal
from backend.util.config import ChubConfig, InstanceDetail
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _seed(db, key, instance, tmdb):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, title, tmdb_id, "
        "asset_type, matched) VALUES (?, ?, ?, ?, 'movie', 1)",
        (key, instance, f"Title {tmdb}", tmdb),
    )


@pytest.fixture
def heal(monkeypatch, tmp_path):
    """Self-Heal with radarr_main configured; `heal.sync(db)` is what Radarr holds now."""
    cfg = ChubConfig()
    cfg.instances.radarr["radarr_main"] = InstanceDetail(url="http://radarr:7878", api="key")
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    state = SimpleNamespace(maps=[], ok=True, sync=lambda db: None)

    class _Connector:
        def __init__(self, db, logger, instance_map):
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

    monkeypatch.setattr("backend.util.connector.Connector", _Connector)
    module = PosterSelfHeal.__new__(PosterSelfHeal)
    module.logger = _logger()
    module.full_config = cfg
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db"), quiet=True) as db:
        _seed(db, "k1", "radarr_main", 101)
        _seed(db, "k2", "radarr_removed", 202)
        state.db = db
        state.module = module
        yield state


def test_index_holds_the_resynced_media_of_configured_instances_only(heal):
    heal.sync = lambda db: _seed(db, "k3", "radarr_main", 303)

    index = heal.module._fresh_media_index(heal.db)

    assert {tmdb for _kind, tmdb in index["tmdb"]} == {101, 303}
    assert heal.maps == [{"arrs": ["radarr_main"], "plex": {}}]


def test_no_index_when_the_resync_fails(heal):
    heal.ok = False

    index = heal.module._fresh_media_index(heal.db)

    assert index is None


@pytest.mark.parametrize("index, reaches_reviews", [(None, False), ({}, True)])
def test_run_stops_before_any_proposal_without_a_fresh_index(
    heal, monkeypatch, tmp_path, index, reaches_reviews
):
    reviews_opened = []

    class _SameDB:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return heal.db

        def __exit__(self, *exc):
            return False

    def stop_at_reviews(db):
        reviews_opened.append(db)
        raise LookupError("reached the review queue")

    modname = "backend.modules.poster_self_heal"
    monkeypatch.setattr(f"{modname}.ChubDB", _SameDB)
    monkeypatch.setattr(f"{modname}.local_dirs_for", lambda cl2k: [str(tmp_path)])
    monkeypatch.setattr(f"{modname}.drive_twins", lambda cl2k: ([], lambda t: None))
    monkeypatch.setattr(
        f"{modname}.TMDBClient", lambda *a, **k: SimpleNamespace(enabled=True)
    )
    monkeypatch.setattr(f"{modname}.poster_heal_review_for", stop_at_reviews)
    monkeypatch.setattr(PosterSelfHeal, "_fresh_media_index", lambda self, db: index)
    heal.module.config = SimpleNamespace(auto_apply=True)

    if reaches_reviews:
        with pytest.raises(LookupError):
            heal.module.run()
    else:
        heal.module.run()

    assert bool(reviews_opened) is reaches_reviews

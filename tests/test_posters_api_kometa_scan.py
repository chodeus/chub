import os
from types import SimpleNamespace

from backend.util.config import ChubConfig
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def test_resolve_plex_match_via_plex_mapping(tmp_path):
    from backend.modules.poster_cleanarr import _stale_plex_match_map

    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query(
            "INSERT INTO plex_media_cache (id, plex_id, instance_name, title, year) "
            "VALUES (?,?,?,?,?)",
            (5, "12345", "Chodeus", "Euphoria", 2019),
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key, instance_name, tvdb_id, "
            "plex_mapping_id, asset_type, matched) VALUES (?,?,?,?,?,1)",
            ("k", "sonarr", 367118, 5, "show"),
        )
        m = _stale_plex_match_map(db, [("tvdb", 367118)])
        # rating_key for the drifted-cache fallback, plus the Plex title+year
        # the UI matches on when the rating_key no longer lines up with a bundle.
        assert m[("tvdb", 367118)] == {
            "rating_key": 12345,
            "title": "Euphoria",
            "year": 2019,
        }


def test_cleanup_overrides_parse_stale():
    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    ov = build_cleanup_overrides(
        {
            "mode": "remove",
            "stale_duplicates_enabled": True,
            "stale_duplicates_mode": "move",
        },
        ChubConfig(),
    )
    assert ov["mode"] == "remove"
    assert ov["stale_duplicates_enabled"] is True
    assert ov["stale_duplicates_mode"] == "move"


def test_cleanup_overrides_parse_overlays_only():
    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    cfg = ChubConfig()
    assert (
        build_cleanup_overrides({"overlays_only": True}, cfg)["overlays_only"] is True
    )
    assert (
        build_cleanup_overrides({"overlays_only": False}, cfg)["overlays_only"] is False
    )
    # absent -> not in overrides (module keeps its saved overlays_only)
    assert "overlays_only" not in build_cleanup_overrides({"mode": "report"}, cfg)


def test_cleanup_overrides_allows_nothing_and_rejects_bad_stale_mode():
    import pytest

    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    cfg = ChubConfig()
    # 'nothing' is allowed for the bloat mode (UI runs stale/orphan with bloat off)
    assert build_cleanup_overrides({"mode": "nothing"}, cfg)["mode"] == "nothing"
    with pytest.raises(ValueError):
        build_cleanup_overrides(
            {"mode": "report", "stale_duplicates_mode": "nuke"}, cfg
        )


def test_cleanup_overrides_rejects_non_string_mode():
    """A non-string mode is a 400, not an AttributeError escaping as a 500."""
    import pytest

    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    cfg = ChubConfig()
    with pytest.raises(ValueError):
        build_cleanup_overrides({"mode": 5}, cfg)
    # absent / None still default to report
    assert build_cleanup_overrides({"mode": None}, cfg)["mode"] == "report"
    assert build_cleanup_overrides({}, cfg)["mode"] == "report"


def test_cleanup_overrides_rejects_non_bool_flags():
    """bool("false") is True — a malformed flag must never enable a deleting pass."""
    import pytest

    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    cfg = ChubConfig()
    for key in (
        "orphan_assets_enabled",
        "stale_duplicates_enabled",
        "overlays_only",
    ):
        with pytest.raises(ValueError):
            build_cleanup_overrides({"mode": "remove", key: "false"}, cfg)


def test_cleanup_overrides_rejects_non_string_sub_modes():
    """A malformed sub-mode is rejected instead of silently falling back to config."""
    import pytest

    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    cfg = ChubConfig()
    for key in ("orphan_assets_mode", "stale_duplicates_mode"):
        with pytest.raises(ValueError):
            build_cleanup_overrides({"mode": "remove", key: 5}, cfg)
        # None keeps "not specified" — the module's saved mode applies
        assert key not in build_cleanup_overrides({"mode": "remove", key: None}, cfg)


def test_cleanup_overrides_confines_asset_dirs(tmp_path):
    """A configured asset_dir survives the guard and comes back resolved."""
    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    assets = tmp_path / "assets"
    assets.mkdir()
    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(tmp_path)]

    ov = build_cleanup_overrides({"asset_dirs": [str(assets) + "/."]}, cfg)

    assert ov["asset_dirs"] == [os.path.realpath(str(assets))]


def test_cleanup_overrides_rejects_asset_dirs_outside_roots(tmp_path):
    """An outside dir raises before it can reach the deleting cleanup passes."""
    import pytest

    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(tmp_path)]

    with pytest.raises(ValueError):
        build_cleanup_overrides({"asset_dirs": ["/etc"]}, cfg)


ORPHAN_URL = "/api/posters/plex-metadata/orphan"


def _client(db):
    """The posters router on a bare app, with the cleanarr logger stubbed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import backend.api.main as apimain
    import backend.api.posters as posters
    from backend.api.posters._shared import get_cleanarr_logger
    from backend.util.config import ConfigError

    app = FastAPI()
    app.state.logger = _logger()
    app.state.db = db
    app.add_exception_handler(ConfigError, apimain.handle_config_error)
    app.include_router(posters.router)
    app.dependency_overrides[get_cleanarr_logger] = _logger
    return TestClient(app, raise_server_exceptions=False)


def test_orphan_delete_route_maps_each_outcome(tmp_path, monkeypatch):
    seen = []
    left = [{"path": "/assets/y.jpg", "parsed": "y", "size": 1}]
    monkeypatch.setattr("backend.util.config.load_config", ChubConfig)
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        client = _client(db)
        for outcome, status in (("deleted", 200), ("not_orphan", 409), ("failed", 400)):
            monkeypatch.setattr(
                "backend.modules.poster_cleanarr.delete_orphan_asset",
                lambda _db, path, _cfg, _log, o=outcome: seen.append(path) or (o, left),
            )
            res = client.request("DELETE", ORPHAN_URL, json={"path": "/assets/x.jpg"})
            assert res.status_code == status, outcome
            assert res.json()["data"]["orphans"] == left, outcome
    assert seen == ["/assets/x.jpg"] * 3


def test_orphan_delete_route_rejects_a_missing_path_before_scanning(
    tmp_path, monkeypatch
):
    called = []
    monkeypatch.setattr(
        "backend.modules.poster_cleanarr.delete_orphan_asset",
        lambda *a: called.append(a) or ("deleted", []),
    )
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        client = _client(db)
        for body in ({}, {"path": ""}, {"path": 5}):
            res = client.request("DELETE", ORPHAN_URL, json=body)
            assert res.status_code == 400
    assert called == []


def test_orphan_delete_route_deletes_a_real_orphan(tmp_path, monkeypatch):
    """End to end through the threadpool hop, with the real scan behind it."""
    from backend.modules.poster_cleanarr import invalidate_kometa_assets_cache
    from backend.util.normalization import normalize_titles

    assets = tmp_path / "assets"
    assets.mkdir()
    gone = assets / "Gone Movie (2019).jpg"
    gone.write_bytes(b"x")
    keeper = assets / "Keeper (2020).jpg"
    keeper.write_bytes(b"x")
    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(tmp_path)]
    cfg.poster_cleanarr.asset_dirs = [str(assets)]
    cfg.poster_cleanarr.orphan_instances = ["radarr1"]
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    invalidate_kometa_assets_cache()
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
            "asset_type) VALUES (?,?,?,?)",
            ("k1", "radarr1", normalize_titles("Keeper (2020)"), "movie"),
        )
        client = _client(db)
        spared = client.request("DELETE", ORPHAN_URL, json={"path": str(keeper)})
        res = client.request("DELETE", ORPHAN_URL, json={"path": str(gone)})

    assert spared.status_code == 409
    assert [o["path"] for o in spared.json()["data"]["orphans"]] == [str(gone)]
    assert keeper.exists()
    assert res.status_code == 200
    assert res.json()["data"]["orphans"] == []
    assert not gone.exists()


def test_cleanup_route_reports_a_run_already_in_flight(tmp_path, monkeypatch):
    """A second request collapses onto the first job; its overrides never apply."""
    cfg = ChubConfig()
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        client = _client(db)
        first = client.post("/api/posters/plex-metadata/cleanup", json={"mode": "report"})
        second = client.post(
            "/api/posters/plex-metadata/cleanup",
            json={"mode": "nothing", "orphan_assets_enabled": True},
        )

    assert first.status_code == 200
    assert not first.json()["data"].get("deduped")
    assert second.status_code == 200
    assert second.json()["data"]["deduped"] is True
    assert second.json()["data"]["job_id"] == first.json()["data"]["job_id"]


def test_orphan_delete_route_fails_closed_without_config(tmp_path, monkeypatch):
    """An unreadable config is a 503 and no delete, as /gdrive/delete-local."""
    called = []
    monkeypatch.setattr(
        "backend.modules.poster_cleanarr.delete_orphan_asset",
        lambda *a: called.append(a) or "deleted",
    )

    def _unreadable():
        raise OSError("config.yml unreadable")

    monkeypatch.setattr("backend.util.config.load_config", _unreadable)
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        res = _client(db).request("DELETE", ORPHAN_URL, json={"path": "/assets/x.jpg"})

    assert res.status_code == 503
    assert res.json()["error_code"] == "CONFIG_UNAVAILABLE"
    assert called == []

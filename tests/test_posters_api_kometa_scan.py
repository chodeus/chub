from types import SimpleNamespace

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
        }
    )
    assert ov["mode"] == "remove"
    assert ov["stale_duplicates_enabled"] is True
    assert ov["stale_duplicates_mode"] == "move"


def test_cleanup_overrides_parse_overlays_only():
    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    assert build_cleanup_overrides({"overlays_only": True})["overlays_only"] is True
    assert build_cleanup_overrides({"overlays_only": False})["overlays_only"] is False
    # absent -> not in overrides (module keeps its saved overlays_only)
    assert "overlays_only" not in build_cleanup_overrides({"mode": "report"})


def test_cleanup_overrides_allows_nothing_and_rejects_bad_stale_mode():
    import pytest

    from backend.util.poster_cleanarr_settings import build_cleanup_overrides

    # 'nothing' is allowed for the bloat mode (UI runs stale/orphan with bloat off)
    assert build_cleanup_overrides({"mode": "nothing"})["mode"] == "nothing"
    with pytest.raises(ValueError):
        build_cleanup_overrides({"mode": "report", "stale_duplicates_mode": "nuke"})

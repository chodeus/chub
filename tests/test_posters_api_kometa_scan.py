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


def test_resolve_rating_keys_via_plex_mapping(tmp_path):
    from backend.api.posters import _stale_rating_key_map

    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query(
            "INSERT INTO plex_media_cache (id, plex_id, instance_name) VALUES (?,?,?)",
            (5, "12345", "Chodeus"),
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key, instance_name, tvdb_id, "
            "plex_mapping_id, asset_type, matched) VALUES (?,?,?,?,?,1)",
            ("k", "sonarr", 367118, 5, "show"),
        )
        m = _stale_rating_key_map(db, [("tvdb", 367118)])
        assert m[("tvdb", 367118)] == 12345


def test_cleanup_overrides_parse_stale():
    from backend.api.posters import _build_cleanup_overrides

    ov = _build_cleanup_overrides(
        {
            "mode": "remove",
            "stale_duplicates_enabled": True,
            "stale_duplicates_mode": "move",
        }
    )
    assert ov["mode"] == "remove"
    assert ov["stale_duplicates_enabled"] is True
    assert ov["stale_duplicates_mode"] == "move"


def test_cleanup_overrides_allows_nothing_and_rejects_bad_stale_mode():
    import pytest

    from backend.api.posters import _build_cleanup_overrides

    # 'nothing' is allowed for the bloat mode (UI runs stale/orphan with bloat off)
    assert _build_cleanup_overrides({"mode": "nothing"})["mode"] == "nothing"
    with pytest.raises(ValueError):
        _build_cleanup_overrides({"mode": "report", "stale_duplicates_mode": "nuke"})

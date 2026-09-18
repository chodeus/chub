from types import SimpleNamespace

from backend.util.config import PosterRenamerrConfig
from backend.util.connector import build_instance_map, gather_media_and_collections


def test_build_instance_map_from_plex_scope():
    cfg = PosterRenamerrConfig(
        instances=["Radarr", "Sonarr"],
        plex_scope=[
            {"instance": "Plex", "library_names": ["Movies"], "match_collections": True}
        ],
    )
    m = build_instance_map(cfg)
    assert sorted(m["arrs"]) == ["Radarr", "Sonarr"]
    assert m["plex"] == {"Plex": ["Movies"]}


def test_build_instance_map_empty_libraries_is_all():
    cfg = PosterRenamerrConfig(
        instances=[],
        plex_scope=[
            {"instance": "Plex", "library_names": [], "match_collections": True}
        ],
    )
    assert build_instance_map(cfg)["plex"] == {"Plex": []}


def _make_db(media_rows=None, collection_rows=None):
    """Minimal fake db for gather_media_and_collections tests."""

    class FakeMedia:
        def get_by_instance(self, name):
            return media_rows or []

    class FakeColl:
        def get_by_instance_and_library(self, inst, lib):
            return collection_rows or []

        def get_library_names_for_instance(self, inst):
            return []

    return SimpleNamespace(media=FakeMedia(), collection=FakeColl())


def test_gather_match_collections_false_returns_no_collections():
    """match_collections=False must contribute zero collection rows."""
    cfg = PosterRenamerrConfig(
        instances=[],
        plex_scope=[
            {
                "instance": "Plex",
                "library_names": ["Movies"],
                "match_collections": False,
            }
        ],
    )
    db = _make_db(collection_rows=[{"id": 99, "asset_type": "collection"}])
    rows = gather_media_and_collections(cfg, db)
    assert rows == []


def test_gather_match_collections_true_returns_collection_rows():
    """match_collections=True must include collection rows the db yields."""
    cfg = PosterRenamerrConfig(
        instances=[],
        plex_scope=[
            {
                "instance": "Plex",
                "library_names": ["Movies"],
                "match_collections": True,
            }
        ],
    )
    db = _make_db(collection_rows=[{"id": 99, "asset_type": "collection"}])
    rows = gather_media_and_collections(cfg, db)
    assert len(rows) == 1
    assert rows[0]["id"] == 99

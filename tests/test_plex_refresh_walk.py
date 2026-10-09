"""walk_plex_libraries must report only the libraries its walk actually refreshed."""

from backend.util import plex_refresh
from backend.util.database import ChubDB


def _plex_row(plex_id, library):
    return {
        "plex_id": plex_id,
        "instance_name": "plex_main",
        "asset_type": "movie",
        "library_name": library,
        "title": f"Title {plex_id}",
        "normalized_title": f"title{plex_id}",
        "year": "2024",
        "guids": {},
        "labels": [],
        "season_number": None,
    }


def test_walk_returns_only_libraries_it_stamped(monkeypatch, tmp_path, stub_logger):
    seen = {}
    with ChubDB(stub_logger, db_path=str(tmp_path / "chub.db"), quiet=True) as db:
        db.plex.execute_query(
            "INSERT INTO plex_media_cache (plex_id, instance_name, library_name, "
            "title, updated_at) VALUES ('900', 'plex_main', 'TV', 'Old Show', "
            "'2020-01-01 00:00:00')"
        )

        class _Connector:
            def __init__(self, db, logger, instance_map):
                seen["instance_map"] = instance_map

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def update_plex_database(self):
                # TV fails silently, as _sync_single_plex_instance does; Anime was never walked
                db.plex.sync_for_library("plex_main", "Movies", [_plex_row("1", "Movies")])
                return []

        monkeypatch.setattr("backend.util.connector.Connector", _Connector)
        libraries = {"plex_main": ["Movies", "TV", "Anime"]}
        refreshed = plex_refresh.walk_plex_libraries(db, stub_logger, libraries)

    assert refreshed == {("plex_main", "Movies")}
    assert seen["instance_map"] == {"plex": libraries}

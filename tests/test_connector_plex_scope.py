from backend.util.connector import build_instance_map
from backend.util.config import PosterRenamerrConfig


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

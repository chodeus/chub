from backend.util.config import (
    PlexScope,
    PosterRenamerrConfig,
    UnmatchedAssetsConfig,
)


def test_plexscope_defaults():
    s = PlexScope(instance="Plex")
    assert s.library_names == []
    assert s.add_posters is False
    assert s.match_collections is False


def test_new_split_shape_validates():
    c = PosterRenamerrConfig(
        instances=["Radarr", "Sonarr"],
        plex_scope=[
            {
                "instance": "Plex",
                "library_names": ["Movies"],
                "add_posters": True,
                "match_collections": True,
            }
        ],
    )
    assert c.instances == ["Radarr", "Sonarr"]
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].add_posters is True
    assert c.plex_scope[0].match_collections is True


def test_legacy_union_shape_is_coerced_poster():
    c = PosterRenamerrConfig(
        instances=[
            "Radarr",
            {"Plex": {"library_names": ["Movies"], "add_posters": True}},
        ]
    )
    assert c.instances == ["Radarr"]
    assert len(c.plex_scope) == 1
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].library_names == ["Movies"]
    assert c.plex_scope[0].add_posters is True
    assert c.plex_scope[0].match_collections is True


def test_legacy_union_empty_libraries_sets_match_collections_false():
    c = PosterRenamerrConfig(
        instances=["Radarr", {"Plex": {"library_names": [], "add_posters": True}}]
    )
    assert c.plex_scope[0].match_collections is False
    assert c.plex_scope[0].add_posters is True


def test_legacy_union_shape_is_coerced_unmatched():
    c = UnmatchedAssetsConfig(
        instances=["Radarr", {"Plex": {"library_names": ["Movies"]}}]
    )
    assert c.instances == ["Radarr"]
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].library_names == ["Movies"]

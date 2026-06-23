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


def test_split_legacy_idempotent_on_already_split():
    from backend.util.config import _split_legacy_instances

    payload = {
        "instances": ["Radarr"],
        "plex_scope": [
            {
                "instance": "Plex",
                "library_names": ["Movies"],
                "add_posters": True,
                "match_collections": True,
            }
        ],
    }
    assert _split_legacy_instances(payload) == payload


def test_split_legacy_merges_preexisting_plex_scope():
    from backend.util.config import _split_legacy_instances

    payload = {
        "instances": ["Radarr", {"Plex2": {"library_names": ["TV"]}}],
        "plex_scope": [
            {
                "instance": "Plex1",
                "library_names": [],
                "add_posters": True,
                "match_collections": False,
            }
        ],
    }
    out = _split_legacy_instances(payload)
    names = [s["instance"] for s in out["plex_scope"]]
    assert "Plex1" in names and "Plex2" in names


def test_asset_renamerr_legacy_coercion():
    from backend.util.config import AssetRenamerrConfig

    c = AssetRenamerrConfig(
        instances=[
            "Radarr",
            {"Plex": {"library_names": ["Movies"], "add_posters": True}},
        ]
    )
    assert c.instances == ["Radarr"]
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].add_posters is True

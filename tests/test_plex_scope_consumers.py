"""Tests for plex_scope consumer migration (Task 3b).

Covers:
* AssetRenamerr._enabled_plex_instances reads from plex_scope (not old dict
  instances shape).
* _check_plex_upload_enabled (job_processor) returns True/False based on
  plex_scope.add_posters, False when plex_scope is absent.
"""

from types import SimpleNamespace


from backend.util.config import AssetRenamerrConfig, PosterRenamerrConfig
from backend.modules.asset_renamerr import AssetRenamerr
from backend.modules.poster_renamerr import PosterRenamerr
from backend.util.job_processor import _check_plex_upload_enabled


# ---------------------------------------------------------------------------
# AssetRenamerr._enabled_plex_instances
# ---------------------------------------------------------------------------


def _make_asset_module(config: AssetRenamerrConfig) -> AssetRenamerr:
    """Build an AssetRenamerr without triggering ChubModule.__init__."""
    m = object.__new__(AssetRenamerr)
    m.logger = None
    m._cancel_event = None
    m._plex_clients = {}
    m.config = config
    m.full_config = SimpleNamespace(
        tmdb=SimpleNamespace(apikey="", cache_expiration=60),
        fanart=SimpleNamespace(client_key="", cache_expiration=2),
        instances=SimpleNamespace(plex={}),
    )
    return m


def test_asset_enabled_plex_instances_from_plex_scope():
    mod = _make_asset_module(
        AssetRenamerrConfig(
            instances=["Radarr"],
            plex_scope=[
                {"instance": "Plex", "library_names": ["Movies"], "add_posters": True},
                {"instance": "Plex2", "library_names": [], "add_posters": False},
            ],
        )
    )
    assert mod._enabled_plex_instances() == [("Plex", ["Movies"])]


def test_asset_enabled_plex_instances_empty_plex_scope():
    mod = _make_asset_module(
        AssetRenamerrConfig(
            instances=["Radarr"],
            plex_scope=[],
        )
    )
    assert mod._enabled_plex_instances() == []


def test_asset_enabled_plex_instances_multiple_enabled():
    mod = _make_asset_module(
        AssetRenamerrConfig(
            instances=["Radarr"],
            plex_scope=[
                {"instance": "Plex", "library_names": ["Movies"], "add_posters": True},
                {"instance": "Plex2", "library_names": ["TV"], "add_posters": True},
            ],
        )
    )
    assert mod._enabled_plex_instances() == [("Plex", ["Movies"]), ("Plex2", ["TV"])]


def test_asset_enabled_plex_instances_empty_library_names():
    """Empty library_names (= all libraries) must be preserved as empty list."""
    mod = _make_asset_module(
        AssetRenamerrConfig(
            instances=["Radarr"],
            plex_scope=[
                {"instance": "Plex", "library_names": [], "add_posters": True},
            ],
        )
    )
    assert mod._enabled_plex_instances() == [("Plex", [])]


# ---------------------------------------------------------------------------
# _check_plex_upload_enabled (job_processor)
# ---------------------------------------------------------------------------


def test_check_plex_upload_enabled_true():
    config = AssetRenamerrConfig(
        instances=["Radarr"],
        plex_scope=[
            {"instance": "Plex", "library_names": ["Movies"], "add_posters": True},
        ],
    )
    assert _check_plex_upload_enabled(config) is True


def test_check_plex_upload_enabled_false_no_add_posters():
    config = AssetRenamerrConfig(
        instances=["Radarr"],
        plex_scope=[
            {"instance": "Plex", "library_names": ["Movies"], "add_posters": False},
        ],
    )
    assert _check_plex_upload_enabled(config) is False


def test_check_plex_upload_enabled_false_empty_scope():
    config = AssetRenamerrConfig(
        instances=["Radarr"],
        plex_scope=[],
    )
    assert _check_plex_upload_enabled(config) is False


def test_check_plex_upload_enabled_no_plex_scope_attr():
    """Config objects without plex_scope must return False gracefully."""
    config = SimpleNamespace(instances=["Radarr"])
    assert _check_plex_upload_enabled(config) is False


def test_check_plex_upload_enabled_poster_renamerr_config_true():
    config = PosterRenamerrConfig(
        instances=["Radarr"],
        plex_scope=[{"instance": "Plex", "add_posters": True}],
    )
    assert _check_plex_upload_enabled(config) is True


def test_check_plex_upload_enabled_poster_renamerr_config_false():
    config = PosterRenamerrConfig(
        instances=["Radarr"],
        plex_scope=[{"instance": "Plex", "add_posters": False}],
    )
    assert _check_plex_upload_enabled(config) is False


# ---------------------------------------------------------------------------
# PosterRenamerr.get_matched_assets — ARR media + plex_scope collections
# ---------------------------------------------------------------------------


def _fake_matched_db(media_rows, collection_rows):
    return SimpleNamespace(
        media=SimpleNamespace(get_by_instance=lambda name: media_rows),
        collection=SimpleNamespace(
            get_by_instance_and_library=lambda inst, lib: collection_rows,
            get_library_names_for_instance=lambda inst: ["Movies"],
        ),
    )


def _make_poster_module(config: PosterRenamerrConfig) -> PosterRenamerr:
    m = object.__new__(PosterRenamerr)
    m.config = config
    m._needs_staging = lambda row: True  # isolate from filesystem staging logic
    return m


def test_get_matched_assets_includes_collections_when_match_collections_true():
    mod = _make_poster_module(
        PosterRenamerrConfig(
            instances=["Radarr"],
            plex_scope=[
                {
                    "instance": "Plex",
                    "library_names": ["Movies"],
                    "match_collections": True,
                }
            ],
        )
    )
    db = _fake_matched_db(
        media_rows=[{"matched": True, "id": "arr1"}],
        collection_rows=[{"matched": True, "id": "coll1"}],
    )
    assert {row["id"] for row in mod.get_matched_assets(db)} == {"arr1", "coll1"}


def test_get_matched_assets_excludes_collections_when_match_collections_false():
    mod = _make_poster_module(
        PosterRenamerrConfig(
            instances=["Radarr"],
            plex_scope=[
                {
                    "instance": "Plex",
                    "library_names": ["Movies"],
                    "match_collections": False,
                }
            ],
        )
    )
    db = _fake_matched_db(
        media_rows=[{"matched": True, "id": "arr1"}],
        collection_rows=[{"matched": True, "id": "coll1"}],
    )
    assert {row["id"] for row in mod.get_matched_assets(db)} == {"arr1"}

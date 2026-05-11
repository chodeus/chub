"""Tests for backend/modules/unmatched_assets.py — pure filtering/grouping logic."""

from types import SimpleNamespace

import pytest

from backend.modules.unmatched_assets import UnmatchedAssets


def make_module():
    """Bypass __init__ (which needs full config + DB) and inject defaults."""
    m = object.__new__(UnmatchedAssets)
    m.config = SimpleNamespace(
        instances=[],
        ignore_folders=[],
        ignore_profiles=[],
        ignore_titles=[],
        ignore_tags=[],
        ignore_collections=[],
        ignore_unmonitored=False,
    )
    m.allowed_instances = set()
    m.plex_libraries = {}
    m.unmatched_media = []
    m.unmatched_collections = []
    m.all_media = []
    m.all_collections = []
    return m


# --- compute_instance_filters ---


def test_compute_instance_filters_string_list():
    m = make_module()
    m.config.instances = ["radarr_main", "sonarr_main"]
    m.compute_instance_filters()
    assert m.allowed_instances == {"radarr_main", "sonarr_main"}
    assert m.plex_libraries == {}


def test_compute_instance_filters_plex_dict_form():
    m = make_module()
    m.config.instances = [
        {"plex_main": {"library_names": ["Movies", "Shows"]}},
        "radarr_main",
    ]
    m.compute_instance_filters()
    assert m.allowed_instances == {"plex_main", "radarr_main"}
    assert m.plex_libraries["plex_main"] == {"Movies", "Shows"}


# --- allowed_media / allowed_collection ---


def test_allowed_media_filters_by_instance():
    m = make_module()
    m.allowed_instances = {"radarr_main"}
    assert m.allowed_media({"instance_name": "radarr_main"}) is True
    assert m.allowed_media({"instance_name": "sonarr_main"}) is False
    assert m.allowed_media({}) is False


def test_allowed_collection_blocks_unconfigured_library():
    m = make_module()
    m.allowed_instances = {"plex_main"}
    m.plex_libraries = {"plex_main": {"Movies"}}
    assert (
        m.allowed_collection({"instance_name": "plex_main", "library_name": "Movies"})
        is True
    )
    assert (
        m.allowed_collection({"instance_name": "plex_main", "library_name": "Anime"})
        is False
    )


def test_allowed_collection_respects_ignore_titles():
    m = make_module()
    m.allowed_instances = {"plex_main"}
    m.config.ignore_collections = ["Spoof Collection"]
    asset = {
        "instance_name": "plex_main",
        "library_name": "Movies",
        "title": "Spoof Collection",
    }
    assert m.allowed_collection(asset) is False


# --- should_include ---


def test_should_include_filters_unmonitored():
    m = make_module()
    m.config.ignore_unmonitored = True
    assert m.should_include({"monitored": False}) is False
    assert m.should_include({"monitored": True}) is True
    # monitored absent -> allowed
    assert m.should_include({}) is True


def test_should_include_filters_folders():
    m = make_module()
    m.config.ignore_folders = ["/skip"]
    assert m.should_include({"folder": "/skip"}) is False
    assert m.should_include({"folder": "/keep"}) is True


def test_should_include_filters_profile():
    m = make_module()
    m.config.ignore_profiles = ["Trash"]
    assert m.should_include({"profile": "Trash"}) is False
    # quality_profile alias
    assert m.should_include({"quality_profile": "Trash"}) is False


def test_should_include_filters_tags_list():
    m = make_module()
    m.config.ignore_tags = ["skip"]
    assert m.should_include({"tags": ["other", "skip"]}) is False
    assert m.should_include({"tags": ["other"]}) is True


def test_should_include_filters_tags_from_json_string():
    m = make_module()
    m.config.ignore_tags = ["skip"]
    assert m.should_include({"tags": '["skip", "other"]'}) is False


def test_should_include_filters_tags_from_csv_string():
    m = make_module()
    m.config.ignore_tags = ["skip"]
    assert m.should_include({"tags": "skip, other"}) is False


def test_should_include_filters_titles():
    m = make_module()
    m.config.ignore_titles = ["The Bad One"]
    assert m.should_include({"title": "The Bad One"}) is False
    assert m.should_include({"title": "Some Other"}) is True


# --- group_assets ---


def test_group_assets_movies_and_collections():
    m = make_module()
    m.unmatched_media = [
        {"asset_type": "movie", "title": "M1", "year": 2020},
        {"asset_type": "movie", "title": "M2", "year": 2021},
    ]
    m.unmatched_collections = [{"title": "Some Collection"}]
    m.all_media = [
        {"asset_type": "movie", "title": "M1", "year": 2020},
        {"asset_type": "movie", "title": "M2", "year": 2021},
        {"asset_type": "movie", "title": "M3", "year": 2022},
    ]
    m.all_collections = [{"title": "Some Collection"}, {"title": "Other"}]

    unmatched, all_grouped, all_collections = m.group_assets()
    assert len(unmatched["movies"]) == 2
    assert len(unmatched["collections"]) == 1
    assert len(all_grouped["movies"]) == 3
    assert len(all_collections) == 2


def test_group_assets_series_combines_seasons():
    m = make_module()
    # Two season-level entries for the same show
    m.unmatched_media = [
        {"asset_type": "show", "title": "Show", "year": 2020, "season_number": 1},
        {"asset_type": "series", "title": "Show", "year": 2020, "season_number": 2},
    ]
    unmatched, _, _ = m.group_assets()
    assert len(unmatched["series"]) == 1
    assert sorted(unmatched["series"][0]["missing_seasons"]) == [1, 2]
    assert unmatched["series"][0]["missing_main_poster"] is False


def test_group_assets_series_missing_main_poster():
    m = make_module()
    m.unmatched_media = [
        {"asset_type": "series", "title": "Show", "year": 2020, "season_number": None}
    ]
    unmatched, _, _ = m.group_assets()
    assert unmatched["series"][0]["missing_main_poster"] is True


# --- calculate_stats ---


def test_calculate_stats_full_complete():
    """If nothing is unmatched, percent_complete = 100."""
    m = make_module()
    stats = m.calculate_stats(
        unmatched={"movies": [], "series": [], "collections": []},
        all_media_grouped={
            "movies": [{}],
            "series": [{"seasons": [1, 2]}],
        },
        all_collections_grouped=[{}],
    )
    assert stats["movies"]["percent_complete"] == 100
    assert stats["series"]["percent_complete"] == 100
    assert stats["seasons"]["percent_complete"] == 100
    assert stats["collections"]["percent_complete"] == 100


def test_calculate_stats_handles_empty_library():
    m = make_module()
    stats = m.calculate_stats(
        unmatched={"movies": [], "series": [], "collections": []},
        all_media_grouped={"movies": [], "series": []},
        all_collections_grouped=[],
    )
    assert stats["movies"]["percent_complete"] == 0
    assert stats["series"]["percent_complete"] == 0


def test_calculate_stats_partial_complete():
    m = make_module()
    stats = m.calculate_stats(
        unmatched={
            "movies": [{}, {}],
            "series": [],
            "collections": [],
        },
        all_media_grouped={"movies": [{}, {}, {}, {}], "series": []},
        all_collections_grouped=[],
    )
    # 2 of 4 missing => 50% complete
    assert stats["movies"]["percent_complete"] == 50

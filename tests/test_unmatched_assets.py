"""Tests for backend/modules/unmatched_assets.py — pure filtering/grouping logic."""

from types import SimpleNamespace


from backend.modules.unmatched_assets import UnmatchedAssets
from backend.util.config import UnmatchedAssetsConfig


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


def test_compute_instance_filters_plex_scope_with_libraries():
    m = make_module()
    m.config.instances = ["radarr_main"]
    from backend.util.config import PlexScope

    m.config.plex_scope = [
        PlexScope(instance="plex_main", library_names=["Movies", "Shows"])
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


def test_should_include_filters_unreleased_status():
    """Unreleased status (announced/tba/upcoming/deleted) is filtered only when
    the item isn't already in the library. An item with downloaded content is in
    Plex and can take a poster, so it stays included even with an unreleased
    *arr status (an early/leaked grab, or a Sonarr series still 'upcoming')."""
    m = make_module()
    # Unreleased + no/unknown content -> excluded (nothing in Plex to match).
    for status in ("announced", "tba", "upcoming", "deleted"):
        assert m.should_include({"status": status, "has_content": None}) is False
        assert m.should_include({"status": status, "has_content": 0}) is False
    # Unreleased BUT already in the library (has_content truthy) -> included.
    assert m.should_include({"status": "announced", "has_content": 1}) is True
    assert m.should_include({"status": "upcoming", "has_content": 1}) is True
    # Released / continuing / inCinemas / unknown / missing pass the status gate.
    assert m.should_include({"status": "released", "has_content": 1}) is True
    assert m.should_include({"status": "continuing", "has_content": 1}) is True
    assert m.should_include({"status": "inCinemas", "has_content": 1}) is True
    assert m.should_include({"status": None, "has_content": 1}) is True
    assert m.should_include({"has_content": 1}) is True


def test_should_include_filters_no_content():
    """has_content=0 still excludes (and NULL still falls through)."""
    m = make_module()
    assert m.should_include({"status": "released", "has_content": 0}) is False
    # NULL has_content -> include (status above is the only gate)
    assert m.should_include({"status": "released", "has_content": None}) is True


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
        {"id": 11, "asset_type": "show", "title": "Show", "year": 2020, "season_number": 1},
        {"id": 12, "asset_type": "series", "title": "Show", "year": 2020, "season_number": 2},
    ]
    unmatched, _, _ = m.group_assets()
    assert len(unmatched["series"]) == 1
    assert sorted(unmatched["series"][0]["missing_seasons"]) == [1, 2]
    assert unmatched["series"][0]["missing_main_poster"] is False


def test_group_assets_series_missing_main_poster():
    m = make_module()
    m.unmatched_media = [
        {"id": 10, "asset_type": "series", "title": "Show", "year": 2020, "season_number": None}
    ]
    unmatched, _, _ = m.group_assets()
    assert unmatched["series"][0]["missing_main_poster"] is True


def test_group_assets_keeps_row_ids_on_every_type():
    """Ignore/match address media_cache rows by id. Movies and collections keep
    theirs via dict(row); a grouped series must carry one target per row it
    aggregates, or its row actions silently do nothing."""
    m = make_module()
    m.unmatched_media = [
        {"id": 1, "asset_type": "movie", "title": "M1", "year": 2020},
        {"id": 2, "asset_type": "series", "title": "Show", "year": 2020, "season_number": 1},
        {"id": 3, "asset_type": "series", "title": "Show", "year": 2020, "season_number": None},
        {"id": 4, "asset_type": "series", "title": "Show", "year": 2020, "season_number": 2},
    ]
    m.unmatched_collections = [{"id": 5, "title": "Some Collection"}]

    unmatched, _, _ = m.group_assets()
    assert unmatched["movies"][0]["id"] == 1
    assert unmatched["collections"][0]["id"] == 5

    series = unmatched["series"][0]
    assert sorted(t["id"] for t in series["targets"]) == [2, 3, 4]
    # The show's own row is the season-less target; the other two are seasons.
    by_id = {t["id"]: t["season_number"] for t in series["targets"]}
    assert by_id == {2: 1, 3: None, 4: 2}
    assert series["missing_main_poster"] is True
    assert sorted(series["missing_seasons"]) == [1, 2]


def test_group_assets_series_split_by_instance():
    """The same show unmatched on two *arr instances is two rows. Merging them
    would fan Ignore across both while labelling the row with one instance."""
    m = make_module()
    m.unmatched_media = [
        {
            "id": 101,
            "asset_type": "series",
            "title": "Foundation",
            "year": 2021,
            "season_number": None,
            "instance_name": "sonarr",
        },
        {
            "id": 202,
            "asset_type": "series",
            "title": "Foundation",
            "year": 2021,
            "season_number": None,
            "instance_name": "sonarr_4k",
        },
        {
            "id": 203,
            "asset_type": "series",
            "title": "Foundation",
            "year": 2021,
            "season_number": 1,
            "instance_name": "sonarr_4k",
        },
    ]
    unmatched, _, _ = m.group_assets()
    by_inst = {r["instance_name"]: r for r in unmatched["series"]}
    assert set(by_inst) == {"sonarr", "sonarr_4k"}
    assert [t["id"] for t in by_inst["sonarr"]["targets"]] == [101]
    assert sorted(t["id"] for t in by_inst["sonarr_4k"]["targets"]) == [202, 203]


def test_group_assets_series_targets_survive_row_order():
    """unmatched_media has no ORDER BY, so the show row can arrive after its
    seasons — every row must still land in targets."""
    m = make_module()
    rows = [
        {"id": 7, "asset_type": "series", "title": "S", "year": 2021, "season_number": None},
        {"id": 8, "asset_type": "series", "title": "S", "year": 2021, "season_number": 3},
    ]
    for ordered in (rows, list(reversed(rows))):
        m.unmatched_media = ordered
        unmatched, _, _ = m.group_assets()
        series = unmatched["series"][0]
        assert sorted(t["id"] for t in series["targets"]) == [7, 8]
        assert series["missing_main_poster"] is True
        assert series["missing_seasons"] == [3]


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


# --- ignore filtering + review serialization ---


def test_should_include_hides_ignored():
    m = make_module()
    assert m.should_include({"ignored": 1}) is False
    assert m.should_include({"ignored": 0}) is True
    assert m.should_include({}) is True


def test_serialize_match_row_parses_conflicts_and_status():
    row = {
        "id": 7,
        "title": "Open Season 2",
        "year": 2008,
        "asset_type": "movie",
        "match_status": "needs_review",
        "match_confidence": 0.55,
        "match_reason": "Titles match under loose string comparison",
        "conflict_ids": '[{"title": "Open Season", "tmdb_id": 9988}]',
    }
    out = UnmatchedAssets._serialize_match_row(row, is_collection=False)
    assert out["id"] == 7
    assert out["type"] == "movie"
    assert out["match_status"] == "needs_review"
    assert out["match_confidence"] == 0.55
    assert out["conflicts"] == [{"title": "Open Season", "tmdb_id": 9988}]


def test_serialize_match_row_collection_and_bad_conflict_json():
    row = {"id": 3, "title": "Marvel", "conflict_ids": "not-json"}
    out = UnmatchedAssets._serialize_match_row(row, is_collection=True)
    assert out["type"] == "collection"
    assert out["asset_type"] == "collection"
    assert out["conflicts"] == []


def test_get_review_and_ignored_returns_locked():
    """The third list surfaces user-confirmed (manually locked) rows so the
    UI can offer an Unlock / re-open action."""
    m = make_module()
    m.allowed_instances = {"radarr"}

    media = SimpleNamespace(
        get_needs_review=lambda: [
            {"id": 1, "title": "Review Me", "instance_name": "radarr"}
        ],
        get_ignored=lambda: [
            {"id": 2, "title": "Ignored Me", "instance_name": "radarr"}
        ],
        get_user_confirmed=lambda: [
            {"id": 3, "title": "Locked Me", "instance_name": "radarr"}
        ],
    )
    collection = SimpleNamespace(
        get_needs_review=lambda: [],
        get_ignored=lambda: [],
        get_user_confirmed=lambda: [],
    )
    db = SimpleNamespace(media=media, collection=collection)

    review, ignored, locked = m.get_review_and_ignored(db)
    assert [r["id"] for r in review] == [1]
    assert [r["id"] for r in ignored] == [2]
    assert [r["id"] for r in locked] == [3]


# --- plex_scope shape (new instances + plex_scope split) ---


def test_compute_instance_filters_reads_plex_scope():
    mod = UnmatchedAssets()
    mod.config = UnmatchedAssetsConfig(
        instances=["Radarr"],
        plex_scope=[{"instance": "Plex", "library_names": ["Movies"]}],
    )
    mod.compute_instance_filters()
    assert "Radarr" in mod.allowed_instances
    assert "Plex" in mod.allowed_instances
    assert mod.plex_libraries["Plex"] == {"Movies"}


def test_compute_instance_filters_empty_libraries_means_all():
    mod = UnmatchedAssets()
    mod.config = UnmatchedAssetsConfig(
        instances=[], plex_scope=[{"instance": "Plex", "library_names": []}]
    )
    mod.compute_instance_filters()
    assert "Plex" in mod.allowed_instances
    assert "Plex" not in mod.plex_libraries  # empty == all => no narrowing recorded

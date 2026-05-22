"""Regression tests for backend/util/arr.py:normalize_arr_media — the
Sonarr season normalizer that backs unmatched_assets' has_content check."""

from backend.util.arr import normalize_arr_media


def make_sonarr_item(episodeCount, totalEpisodeCount, episodeFileCount):
    """Build a minimal Sonarr API-shaped item with one season carrying the
    given episode-count combo."""
    return {
        "id": 1,
        "title": "Heated Rivalry",
        "year": 2025,
        "tmdbId": 0,
        "tvdbId": 464461,
        "imdbId": "tt35495073",
        "monitored": True,
        "status": "continuing",
        "path": "/data/media/shows/Heated Rivalry (2025)",
        "tags": [],
        "seasons": [
            {
                "seasonNumber": 1,
                "monitored": True,
                "statistics": {
                    "episodeCount": episodeCount,
                    "totalEpisodeCount": totalEpisodeCount,
                    "episodeFileCount": episodeFileCount,
                },
            }
        ],
    }


def test_season_has_episodes_reflects_files_not_aired():
    """The has_content driver must come from episodeFileCount, not the
    aired-counts. Regression: previously CHUB used episodeCount which
    ticks up as episodes air regardless of whether the user has any
    files on disk — that made unmatched_assets falsely flag every
    future season of a currently-airing show."""
    # Season with 6 aired episodes (episodeCount=6) but ZERO downloaded
    # (episodeFileCount=0). has_content should resolve to False.
    item = make_sonarr_item(episodeCount=6, totalEpisodeCount=10, episodeFileCount=0)
    result = normalize_arr_media(item, tags=[], arr_type="sonarr")

    seasons = result["seasons"]
    assert len(seasons) == 1
    assert seasons[0]["season_has_episodes"] == 0, (
        "season_has_episodes must reflect episodeFileCount (files on disk),"
        " not episodeCount (aired episodes)"
    )


def test_season_has_episodes_counts_actual_files():
    """Conversely: a season with 4 of 10 episodes downloaded should
    yield season_has_episodes=4."""
    item = make_sonarr_item(episodeCount=10, totalEpisodeCount=10, episodeFileCount=4)
    result = normalize_arr_media(item, tags=[], arr_type="sonarr")
    seasons = result["seasons"]
    assert seasons[0]["season_has_episodes"] == 4


def test_show_has_content_rolls_up_per_season_files():
    """The show-level has_content is `any(s.season_has_episodes > 0)`.
    A show whose only season has 0 episodeFileCount should resolve
    has_content=False at the show level too."""
    item = make_sonarr_item(episodeCount=6, totalEpisodeCount=10, episodeFileCount=0)
    result = normalize_arr_media(item, tags=[], arr_type="sonarr")
    assert result["has_content"] is False


def test_show_has_content_true_when_any_season_has_files():
    """If at least one season has files, the show's has_content is True."""
    item = {
        "id": 1,
        "title": "Some Show",
        "year": 2024,
        "monitored": True,
        "status": "continuing",
        "path": "/data/media/shows/Some Show (2024)",
        "tags": [],
        "seasons": [
            {
                "seasonNumber": 1,
                "monitored": True,
                "statistics": {
                    "episodeCount": 10,
                    "totalEpisodeCount": 10,
                    "episodeFileCount": 10,
                },
            },
            {
                "seasonNumber": 2,
                "monitored": True,
                "statistics": {
                    "episodeCount": 5,
                    "totalEpisodeCount": 10,
                    "episodeFileCount": 0,
                },
            },
        ],
    }
    result = normalize_arr_media(item, tags=[], arr_type="sonarr")
    assert result["has_content"] is True


def test_season_pack_still_uses_episodeCount_vs_total():
    """season_pack (whether the season is "complete" per Sonarr's view)
    is still episodeCount == totalEpisodeCount, independent of files.
    A fully-aired season the user hasn't downloaded should still be
    flagged as a season_pack=True candidate."""
    item = make_sonarr_item(episodeCount=10, totalEpisodeCount=10, episodeFileCount=0)
    result = normalize_arr_media(item, tags=[], arr_type="sonarr")
    seasons = result["seasons"]
    assert seasons[0]["season_pack"] is True


def test_missing_statistics_defaults_safely():
    """Sonarr can return seasons without a statistics block (rare; e.g.
    a newly-added series before first scan). season_has_episodes
    should fall back to 0 not crash."""
    item = {
        "id": 1,
        "title": "Some Show",
        "year": 2024,
        "monitored": True,
        "status": "continuing",
        "path": "/data/media/shows/Some Show (2024)",
        "tags": [],
        "seasons": [{"seasonNumber": 1, "monitored": True}],  # no statistics
    }
    result = normalize_arr_media(item, tags=[], arr_type="sonarr")
    assert result["seasons"][0]["season_has_episodes"] == 0

"""Tests for the webhook dedup identity (backend/api/webhooks.py).

Verifies that per-episode webhooks for one season collapse to a single job,
while different seasons and different firing instances stay distinct so their
posters aren't wrongly debounced away.
"""

import pytest

pytest.importorskip("fastapi")

from backend.api.webhooks import _webhook_dedup_identity  # noqa: E402


def _series(season, episode, *, instance="Sonarr", title="Show", tvdb="123"):
    return {
        "eventType": "Download",
        "instanceName": instance,
        "series": {"title": title, "year": 2020, "tvdbId": tvdb},
        "episodes": [{"seasonNumber": season, "episodeNumber": episode}],
    }


def _name(data, client_info=None):
    identity = _webhook_dedup_identity(data, client_info)
    assert identity is not None
    return identity[1]


def test_same_payload_same_identity():
    assert _name(_series(1, 1)) == _name(_series(1, 1))


def test_per_episode_same_season_collapses():
    # Sonarr fires one webhook per episode; same season -> one job.
    assert _name(_series(1, 1)) == _name(_series(1, 2)) == _name(_series(1, 9))


def test_different_seasons_stay_distinct():
    # A second season imported in the same window must NOT be debounced away.
    assert _name(_series(1, 1)) != _name(_series(2, 1))


def test_different_instances_stay_distinct():
    assert _name(_series(1, 1, instance="Sonarr")) != _name(
        _series(1, 1, instance="Anime")
    )


def test_override_instance_beats_payload_name():
    # ?instance= override is the instance discriminator when present.
    a = _name(_series(1, 1), {"instance_override": "HD"})
    b = _name(_series(1, 1), {"instance_override": "4K"})
    assert a != b


def test_added_vs_import_phase_distinct():
    added = dict(_series(1, 1))
    added["eventType"] = "SeriesAdd"
    assert _name(_series(1, 1)) != _name(added)


def test_movie_identity_stable_and_typed():
    movie = {
        "eventType": "Download",
        "instanceName": "Radarr",
        "movie": {"title": "Film", "year": 2019, "tmdbId": "55"},
    }
    identity = _webhook_dedup_identity(movie)
    assert identity is not None
    assert identity[0] == "movie"
    assert _webhook_dedup_identity(movie)[1] == identity[1]


def test_no_media_block_returns_none():
    assert _webhook_dedup_identity({"eventType": "Test"}) is None

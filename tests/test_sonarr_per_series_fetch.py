"""SonarrClient's per-series fan-out: a failed series is None, never an empty list."""

from backend.util.arr import SonarrClient


def _client(responses, stub_logger):
    client = SonarrClient.__new__(SonarrClient)
    client.url = "http://sonarr:8989"
    client.api_version = "v3"
    client.logger = stub_logger
    client.make_get_request_threadsafe = lambda url: responses[url.rsplit("=", 1)[1]]
    return client


def test_episode_files_mark_a_failed_series_none(stub_logger):
    client = _client({"1": [{"path": "/tv/A/S01E01.mkv"}], "2": None}, stub_logger)

    result = client.get_episode_files_by_series([1, 2])

    assert result == {1: [{"path": "/tv/A/S01E01.mkv"}], 2: None}
    assert any("/episodefile for series 2" in m for m in stub_logger.messages["warning"])


def test_episodes_by_series_still_group_by_season_and_map_failures_to_empty(
    stub_logger,
):
    episodes = [{"seasonNumber": 1, "id": 10}, {"seasonNumber": 2, "id": 20}]
    client = _client({"1": episodes, "2": None}, stub_logger)

    result = client._fetch_episodes_by_series([1, 2])

    assert result == {1: {1: [episodes[0]], 2: [episodes[1]]}, 2: {}}

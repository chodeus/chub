"""CHUB's parallel reads from one *arr run on at most 6 threads."""

import threading
import time

import pytest

from backend.modules.upgradinatorr import Upgradinatorr
from backend.util.arr import LidarrClient, SonarrClient


class _Peak:
    """Counts how many calls run at once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = self.peak = 0

    def __call__(self, result):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        time.sleep(0.05)
        with self.lock:
            self.running -= 1
        return result


def _client(cls, api_version, peak, stub_logger):
    client = cls.__new__(cls)
    client.url = "http://arr"
    client.api_version = api_version
    client.logger = stub_logger
    client.make_get_request_threadsafe = lambda url: peak([])
    return client


class _WantedApp:
    instance_name = "lidarr"

    def __init__(self, peak):
        self.peak = peak

    def get_wanted_missing(self, page=1, page_size=100, threadsafe=False):
        result = {
            "records": [{"page": page}] * page_size if page <= 21 else [],
            "totalRecords": 21 * page_size,
        }
        return self.peak(result) if threadsafe else result


def _sonarr_episode_files(peak, stub_logger):
    client = _client(SonarrClient, "v3", peak, stub_logger)
    client.get_episode_files_by_series(list(range(1, 21)))


def _sonarr_episodes(peak, stub_logger):
    client = _client(SonarrClient, "v3", peak, stub_logger)
    client._fetch_episodes_by_series(list(range(1, 21)))


def _lidarr_albums(peak, stub_logger):
    client = _client(LidarrClient, "v1", peak, stub_logger)
    client._fetch_albums_by_artist(list(range(1, 21)))


def _upgradinatorr_wanted_pages(peak, stub_logger):
    module = object.__new__(Upgradinatorr)
    module.logger = stub_logger
    assert len(module._get_all_wanted(_WantedApp(peak), "missing")) == 21 * 200


@pytest.mark.parametrize(
    "read",
    [
        _sonarr_episode_files,
        _sonarr_episodes,
        _lidarr_albums,
        _upgradinatorr_wanted_pages,
    ],
)
def test_reads_run_on_six_threads(read, stub_logger):
    peak = _Peak()

    read(peak, stub_logger)

    assert peak.peak == 6

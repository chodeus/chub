"""Tests for backend/modules/health_checkarr.py — flagged-media deletion."""

import re
from types import SimpleNamespace

import pytest

from backend.modules.health_checkarr import HealthCheckarr
from backend.util.config import ChubConfig, InstanceDetail, InstancesConfig
from backend.util.constants import tmdb_id_regex, tvdb_id_regex


class StubLogger:
    def __init__(self):
        self.deleted = []
        self.info_lines = []

    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        if a:
            self.info_lines.append(a[0])

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def log_outro(self):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


# --- ID extraction patterns used inside run() ---


def test_tmdb_regex_extracts_id_from_health_message():
    msg = "Movies removed from TMDb: title (tmdb 12345)"
    ids = [int(m.group(1)) for m in re.finditer(tmdb_id_regex, msg)]
    assert ids == [12345]


def test_tvdb_regex_extracts_multiple_ids():
    msg = "Series removed from TVDb: foo (tvdb 11) and bar (tvdb 22)"
    ids = [int(m.group(1)) for m in re.finditer(tvdb_id_regex, msg)]
    assert ids == [11, 22]


def test_tmdb_regex_no_match_on_unrelated_text():
    ids = [int(m.group(1)) for m in re.finditer(tmdb_id_regex, "no IDs here")]
    assert ids == []


# --- End-to-end run() with mocked ARR client ---


class FakeARR:
    instance_name = "main"

    def __init__(self, health, media):
        self._health = health
        self._media = media
        self.deleted = []
        self.connected = True

    def is_connected(self):
        return self.connected

    def get_health(self):
        return self._health

    def get_all_media(self):
        return self._media

    def delete_media(self, media_id):
        self.deleted.append(media_id)


def make_module(dry_run=False, report_only=False):
    m = object.__new__(HealthCheckarr)
    m._cancel_event = None
    m.logger = StubLogger()
    m.config = SimpleNamespace(
        log_level="info",
        dry_run=dry_run,
        report_only=report_only,
    )
    m.full_config = ChubConfig(
        instances=InstancesConfig(
            radarr={
                "main": InstanceDetail(url="http://radarr:7878", api="key"),
            }
        )
    )
    return m


def _patch_arr(monkeypatch, fake):
    monkeypatch.setattr(
        "backend.modules.health_checkarr.create_arr_client", lambda *a, **kw: fake
    )
    # Skip notification side effects
    monkeypatch.setattr(
        "backend.modules.health_checkarr.NotificationManager",
        lambda *a, **kw: SimpleNamespace(send_notification=lambda *_a, **_kw: None),
    )


def test_run_deletes_radarr_items_matching_health(monkeypatch):
    fake = FakeARR(
        health=[
            {"source": "RemovedMovieCheck", "message": "tmdb 100"},
            {"source": "RemovedMovieCheck", "message": "tmdb 200"},
        ],
        media=[
            {"tmdb_id": 100, "title": "Deleteme", "media_id": 1},
            {"tmdb_id": 999, "title": "Keep", "media_id": 2},
            {"tmdb_id": 200, "title": "Deleteme2", "media_id": 3},
        ],
    )
    module = make_module(dry_run=False)
    _patch_arr(monkeypatch, fake)
    module.run()
    assert sorted(fake.deleted) == [1, 3]


def test_run_respects_dry_run(monkeypatch):
    fake = FakeARR(
        health=[{"source": "RemovedMovieCheck", "message": "tmdb 100"}],
        media=[{"tmdb_id": 100, "title": "X", "media_id": 1}],
    )
    module = make_module(dry_run=True)
    _patch_arr(monkeypatch, fake)
    module.run()
    assert fake.deleted == []


def test_run_respects_report_only(monkeypatch):
    fake = FakeARR(
        health=[{"source": "RemovedMovieCheck", "message": "tmdb 100"}],
        media=[{"tmdb_id": 100, "title": "X", "media_id": 1}],
    )
    module = make_module(dry_run=False, report_only=True)
    _patch_arr(monkeypatch, fake)
    module.run()
    assert fake.deleted == []


def test_run_skips_unconnected_instance(monkeypatch):
    fake = FakeARR(health=[], media=[])
    fake.connected = False
    module = make_module(dry_run=False)
    _patch_arr(monkeypatch, fake)
    module.run()
    assert fake.deleted == []


def test_run_with_no_health_items_does_nothing(monkeypatch):
    fake = FakeARR(
        health=None,
        media=[{"tmdb_id": 1, "title": "X", "media_id": 1}],
    )
    module = make_module(dry_run=False)
    _patch_arr(monkeypatch, fake)
    module.run()
    assert fake.deleted == []


def test_run_ignores_unrelated_health_sources(monkeypatch):
    """Only RemovedMovieCheck / RemovedSeriesCheck trigger deletions."""
    fake = FakeARR(
        health=[{"source": "OtherCheck", "message": "tmdb 100"}],
        media=[{"tmdb_id": 100, "title": "X", "media_id": 1}],
    )
    module = make_module(dry_run=False)
    _patch_arr(monkeypatch, fake)
    module.run()
    assert fake.deleted == []

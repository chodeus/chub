"""Pins finishing a slow search on the next run instead of searching it again."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

import backend.modules.upgradinatorr as upgradinatorr_module
from backend.util.arr import COMMAND_TIMEOUT, RadarrClient, RetryHandler
from backend.util.database import ChubDB
from backend.util.upgradinatorr_notification import build_upgradinatorr_embeds

from tests.test_config import FakeARR, StubLogger, make_upgradinatorr


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = str(tmp_path / "chub.db")
    real = upgradinatorr_module.ChubDB
    monkeypatch.setattr(
        upgradinatorr_module, "ChubDB", lambda **kwargs: real(db_path=path, **kwargs)
    )
    return path


def _inflight(path):
    with ChubDB(logger=StubLogger(), db_path=path) as db:
        return db.upgradinatorr_inflight.get("radarr")


def _stage(path, **row):
    with ChubDB(logger=StubLogger(), db_path=path) as db:
        db.upgradinatorr_inflight.stage("radarr", **row)


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _movie(media_id):
    return {
        "title": f"Movie {media_id}",
        "year": 2001,
        "media_id": media_id,
        "monitored": True,
        "status": "released",
        "seasons": None,
        "tags": [],
    }


class _SlowARR(FakeARR):
    """Searches finish except those in ``slow``; command states and grab history are scripted."""

    history_import_event = 3
    history_upgrade_delete_event = 6
    history_failed_event = 4
    upgrade_pair_field = "movieId"

    def __init__(self, movies, slow=(), command_states=None, history=None):
        super().__init__([movies])
        self.slow = set(slow)
        self.command_states = command_states or {}
        self.history = history or {}
        self.searched = []

    def search_media(self, media_id):
        self.searched.append(media_id)
        return {
            "id": 500 + media_id,
            "queued": "2026-11-06T10:00:00Z",
            "body": {"movieIds": [media_id]},
        }

    def wait_for_command_result(self, command_id, label=""):
        return COMMAND_TIMEOUT if command_id - 500 in self.slow else "completed"

    def get_command_state(self, command_id):
        return self.command_states.get(command_id)

    def get_grab_history(self, media_id):
        return self.history.get(media_id, [])

    def get_history_since(self, date, event_type):
        return []


def _settings():
    return SimpleNamespace(
        count=10,
        tag_name="checked",
        ignore_tag="ignore",
        unattended=False,
        season_monitored_threshold=0,
        search_mode="upgrade",
        queue_block_hours=0,
    )


def test_a_search_the_run_stops_waiting_on_is_staged_for_the_next(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _SlowARR([_movie(1), _movie(2), _movie(3)], slow={2})

    module.process_instance("radarr", _settings(), app)

    assert app.searched == [1, 2]
    row = _inflight(isolated_db)
    assert {k: row[k] for k in ("media_id", "child_id", "command_id", "label")} == {
        "media_id": 2,
        "child_id": None,
        "command_id": 502,
        "label": "Movie 2 (2001)",
    }
    # The queued time, so grabs made while this run waited are still found.
    assert row["started_at"].startswith("2026-11-06T10:00:00")


def test_a_still_running_search_holds_the_next_run_back(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    _stage(isolated_db, media_id=2, child_id=None, command_id=502, label="Movie 2 (2001)",
           started_at=_iso(1))
    app = _SlowARR([_movie(1), _movie(2)], command_states={502: {"status": "started"}})

    result = module.process_instance("radarr", _settings(), app)

    assert app.searched == []
    assert app.add_calls == []
    assert result["inflight_running"] == "Movie 2 (2001)"
    assert _inflight(isolated_db)["command_id"] == 502
    [part] = build_upgradinatorr_embeds({"radarr": result})
    assert (
        "Waiting on the last run's search of Movie 2 (2001): nothing new is "
        "searched until it finishes" in part["description"]
    )


def test_a_finished_search_is_tagged_and_reported_not_searched_again(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    start, grabbed = _iso(2), _iso(1)
    _stage(isolated_db, media_id=2, child_id=None, command_id=502, label="Movie 2 (2001)",
           started_at=start)
    history = {
        2: [
            {"downloadId": "new", "movieId": 2, "sourceTitle": "Movie.2.NEW-GRP",
             "eventType": "grabbed", "date": grabbed},
            {"downloadId": "old", "movieId": 2, "sourceTitle": "Movie.2.OLD-GRP",
             "eventType": "grabbed", "date": _iso(30)},
        ]
    }
    app = _SlowARR([_movie(1), _movie(2), _movie(3)],
                   command_states={502: {"status": "completed"}}, history=history)

    result = module.process_instance("radarr", _settings(), app)

    assert app.searched == [1, 3]
    assert (2, 1) in app.add_calls
    entry = next(e for e in result["data"] if e["media_id"] == 2)
    assert [grab["download"] for grab in entry["grabs"]] == ["Movie.2.NEW-GRP"]
    assert result["inflight_finished"] == {"label": "Movie 2 (2001)", "state": "done"}
    assert _inflight(isolated_db) is None
    [part] = build_upgradinatorr_embeds({"radarr": result})
    assert "Finished the last run's search of Movie 2 (2001)" in part["description"]
    # Its own date, not this run's start: the next run's history lookback starts there.
    with ChubDB(logger=StubLogger(), db_path=isolated_db) as db:
        rows = db.upgradinatorr_grabs.pending("radarr")
    assert [(r["download_id"], r["grabbed_at"]) for r in rows] == [("new", grabbed)]


@pytest.mark.parametrize(
    "state, started, expected",
    [
        ({}, 1, "done"),  # the *arr no longer has it
        ({"status": "failed"}, 1, "failed"),
        ({"status": "started"}, 7, "done"),  # given up on after 6 hours
        (None, 1, "running"),  # unreadable: wait rather than search twice
    ],
)
def test_the_staged_search_state(state, started, expected):
    module = make_upgradinatorr(dry_run=False)
    app = SimpleNamespace(get_command_state=lambda command_id: state)

    got = module._inflight_state(app, {"command_id": 1, "started_at": _iso(started)})

    assert got == expected


def test_a_failed_search_is_reported_and_searched_again(isolated_db):
    """It was never tagged, so this run is free to search it like any other."""
    module = make_upgradinatorr(dry_run=False)
    _stage(isolated_db, media_id=2, child_id=None, command_id=502, label="Movie 2 (2001)",
           started_at=_iso(1))
    app = _SlowARR([_movie(2)], command_states={502: {"status": "failed"}})

    result = module.process_instance("radarr", _settings(), app)

    assert app.searched == [2]
    assert [e["media_id"] for e in result["data"]] == [2]
    assert result["inflight_finished"] == {"label": "Movie 2 (2001)", "state": "failed"}
    assert _inflight(isolated_db) is None
    [part] = build_upgradinatorr_embeds({"radarr": result})
    assert "The last run's search of Movie 2 (2001) failed" in part["description"]


def test_a_finished_season_search_is_recorded_as_searched():
    module = make_upgradinatorr(dry_run=False)
    recorded = []
    progress = SimpleNamespace(
        record_processed_child=lambda *args: recorded.append(args)
    )
    app = SimpleNamespace(
        instance_name="sonarr", instance_type="Sonarr",
        get_command_state=lambda command_id: {"status": "completed"},
        add_tags=lambda *args: pytest.fail("a season search must not tag the series"),
    )
    module._get_grabbed_downloads = lambda *args, **kwargs: []
    searched, grabbed = [], {}
    row = {"media_id": 11, "child_id": "2", "command_id": 9, "label": "Show S2",
           "started_at": _iso(1)}

    left = module._resume_inflight(
        app, row, [], [{"media_id": 11}], 1, progress, (searched, grabbed), {}
    )

    assert recorded == [("sonarr", 11, "2")]
    assert left == [{"media_id": 11}]


def test_the_inflight_row_follows_an_instance_rename(tmp_path):
    path = str(tmp_path / "chub.db")
    with ChubDB(logger=StubLogger(), db_path=path) as db:
        db.upgradinatorr_inflight.stage("old", 1, None, 5, "Movie 1")
        db.rename_instance("old", "new", "radarr")
        assert db.upgradinatorr_inflight.get("old") is None
        assert db.upgradinatorr_inflight.get("new")["command_id"] == 5


def test_staging_again_replaces_the_instance_row(tmp_path):
    path = str(tmp_path / "chub.db")
    with ChubDB(logger=StubLogger(), db_path=path) as db:
        db.upgradinatorr_inflight.stage("radarr", 1, None, 5, "Movie 1")
        db.upgradinatorr_inflight.stage("radarr", 2, "3", 6, "Show S3")
        row = db.upgradinatorr_inflight.get("radarr")
        db.upgradinatorr_inflight.clear("radarr")
        assert db.upgradinatorr_inflight.get("radarr") is None
    assert (row["media_id"], row["child_id"], row["command_id"]) == (2, "3", 6)


class _Answer(requests.adapters.BaseAdapter):
    def __init__(self, status, body):
        super().__init__()
        self.status, self.body = status, body

    def send(self, request, **kwargs):
        response = requests.Response()
        response.status_code = self.status
        response.url = request.url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(self.body).encode()
        return response

    def close(self):
        pass


class _ErrorLog(StubLogger):
    def __init__(self):
        super().__init__()
        self.errors = []

    def error(self, *args, **kwargs):
        self.errors.append(args)


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (200, {"status": "started"}, {"status": "started"}),
        (404, {}, {}),  # gone: no ERROR, which would send a failure notification
        (500, {}, None),
    ],
)
def test_command_state_through_the_real_request_path(status, body, expected):
    client = RadarrClient.__new__(RadarrClient)
    client.url = "http://radarr.test"
    client.logger = _ErrorLog()
    client.retry_handler = RetryHandler()
    client.timeout = 5
    client.session = requests.Session()
    client.session.mount("http://", _Answer(status, body))

    assert client.get_command_state(7) == expected
    assert client.logger.errors == []


class _SonarrResumeARR(FakeARR):
    instance_name = "sonarr"
    instance_type = "Sonarr"
    history_import_event = 3
    history_upgrade_delete_event = 5
    history_failed_event = 4
    upgrade_pair_field = "episodeId"

    def __init__(self, series, history):
        super().__init__([series])
        self.season_searches = []
        self.history = history

    def search_season(self, media_id, season_number):
        self.season_searches.append((media_id, season_number))
        return {"id": 700 + season_number}

    def get_command_state(self, command_id):
        return {"status": "completed"}

    def get_season_grab_history(self, media_id, season_number):
        return self.history.get(season_number, [])

    def get_history_since(self, date, event_type):
        return []


def test_a_resumed_season_reports_its_series_once_when_the_run_reaches_it(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    with ChubDB(logger=StubLogger(), db_path=isolated_db) as db:
        db.upgradinatorr_inflight.stage("sonarr", 11, "1", 701, "Show S1", _iso(2))
    series = {
        "title": "Show", "year": 2020, "media_id": 11, "monitored": True,
        "status": "continuing", "tags": [],
        "seasons": [
            {"season_number": 1, "monitored": True, "episode_data": []},
            {"season_number": 2, "monitored": True, "episode_data": []},
        ],
    }
    history = {1: [{"downloadId": "s1", "seriesId": 11, "sourceTitle": "Show.S01-GRP",
                    "eventType": "grabbed", "date": _iso(1)}]}
    app = _SonarrResumeARR([series], history)

    result = module.process_instance("sonarr", _settings(), app)

    # Season 1 finished last run's search; this run searches only season 2.
    assert app.season_searches == [(11, 2)]
    assert [entry["media_id"] for entry in result["data"]] == [11]
    assert [grab["download"] for grab in result["data"][0]["grabs"]] == ["Show.S01-GRP"]

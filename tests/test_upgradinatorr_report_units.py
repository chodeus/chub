"""Pins what each Upgradinatorr count means, in the run log and the notification alike."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import backend.modules.upgradinatorr as upgradinatorr_module
from backend.modules.upgradinatorr import Upgradinatorr
from backend.util.arr import COMMAND_TIMEOUT
from backend.util.database import ChubDB
from backend.util.upgradinatorr_notification import build_upgradinatorr_embeds, summary_lines

from tests.test_config import FakeARR, StubLogger, make_upgradinatorr


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = str(tmp_path / "chub.db")
    real = upgradinatorr_module.ChubDB
    monkeypatch.setattr(
        upgradinatorr_module, "ChubDB", lambda **kwargs: real(db_path=path, **kwargs)
    )
    return path


class _Capture(StubLogger):
    def __init__(self):
        super().__init__()
        self.lines = []

    def info(self, *args, **kwargs):
        self.lines.append(" ".join(str(a) for a in args))


class _SonarrARR(FakeARR):
    """Season searches finish, except the (series, season) pairs in ``slow``."""

    instance_name = "sonarr"
    instance_type = "Sonarr"

    def __init__(self, series, slow=()):
        super().__init__([series])
        self.season_searches = []
        self.slow = set(slow)

    def search_season(self, media_id, season_number):
        self.season_searches.append((media_id, season_number))
        return {
            "id": 1000 * media_id + season_number,
            "queued": "2026-11-10T00:00:00Z",
            "body": {"seriesId": media_id, "seasonNumber": season_number},
        }

    def wait_for_command_result(self, command_id, label=""):
        pair = divmod(command_id, 1000)
        return COMMAND_TIMEOUT if pair in self.slow else "completed"

    def get_season_grab_history(self, media_id, season_number):
        return []


class _QueuedARR(FakeARR):
    """Movie 7 has a download waiting to import."""

    def get_queue(self, page=1, page_size=200):
        added = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return {
            "records": [
                {
                    "downloadId": "dl-7",
                    "movieId": 7,
                    "title": "Movie.7.2001.1080p-GRP",
                    "trackedDownloadState": "importPending",
                    "added": added,
                }
            ]
        }


def _series(media_id, seasons):
    return {
        "title": f"Show {media_id}",
        "year": 2006,
        "media_id": media_id,
        "monitored": True,
        "status": "ended",
        "tags": [],
        "seasons": [
            {"season_number": n, "monitored": True, "episode_data": []}
            for n in range(1, seasons + 1)
        ],
    }


def _movie(media_id, tags=()):
    return {
        "title": f"Movie {media_id}",
        "year": 2001,
        "media_id": media_id,
        "monitored": True,
        "status": "released",
        "seasons": None,
        "tags": list(tags),
    }


def _settings(**overrides):
    base = dict(
        count=1,
        tag_name="checked",
        ignore_tag="ignore",
        unattended=False,
        season_monitored_threshold=0,
        search_mode="upgrade",
        queue_block_hours=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_series_mode_counts_one_series_and_its_season_searches(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    module.logger = _Capture()
    app = _SonarrARR([_series(30, seasons=4), _series(31, seasons=2)])

    result = module.process_instance("sonarr", _settings(), app)

    assert app.season_searches == [(30, 1), (30, 2), (30, 3), (30, 4)]
    assert "Selected 1 of 2 series to search (Count: 1 series a run)." in module.logger.lines
    assert "   → 1 series searched (4 seasons), 1 tagged" in module.logger.lines
    [part] = build_upgradinatorr_embeds({"sonarr": result})
    assert part["description"].split("\n") == [
        "Upgrade search: 1 series searched (4 seasons), 0 grabbed",
        "Progress: 1 of 2 series searched, 1 left (1 more run at 1 a run)",
    ]


def test_season_mode_counts_the_season_searches_count_allowed(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    module.logger = _Capture()
    app = _SonarrARR([_series(30, seasons=4)])

    result = module.process_instance(
        "sonarr", _settings(count=3, count_mode="season_album"), app
    )

    assert len(app.season_searches) == 3
    assert "1 series left to search; this run searches up to 3 seasons." in module.logger.lines
    assert summary_lines(result)[0] == "Upgrade search: 1 series searched (3 seasons), 0 grabbed"


def test_the_log_prints_the_notification_summary_word_for_word(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _SonarrARR([_series(30, seasons=4)])
    result = module.process_instance("sonarr", _settings(), app)

    module.logger = _Capture()
    module.print_output({"sonarr": result})

    [part] = build_upgradinatorr_embeds({"sonarr": result})
    summary = part["description"].split("\n")
    log = module.logger.lines
    start = log.index(summary[0])
    assert log[start : start + len(summary)] == summary
    assert not any(line.startswith("Searches:") for line in log)
    assert "[NO GRABS] 1 series searched, nothing grabbed: Show 30 (2006)" in log


def test_radarr_counts_movies_with_no_child_searches(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = FakeARR([[_movie(1), _movie(2), _movie(3)]])

    result = module.process_instance("radarr", _settings(count=2), app)

    assert summary_lines(result)[0] == "Upgrade search: 2 movies searched, 0 grabbed"


def test_lidarr_counts_artists_and_their_album_searches():
    run = {
        "instance_type": "lidarr",
        "search_mode": "missing",
        "budget": 5,
        "granular": True,
        "searches_attempted": 5,
        "items_searched": 2,
        "child_searches": 5,
        "searches_failed": 1,
        "total_count": 355,
        "tagged_count": 10,
        "data": [],
    }

    assert summary_lines(run)[:2] == [
        "Missing search: 2 artists searched (5 albums), 0 grabbed, 1 search failed",
        "Progress: 10 of 355 artists done before this run",
    ]


def test_a_finished_rotation_says_why_nothing_is_searched(isolated_db):
    """A waiting download keeps the run reporting, so the summary must give the reason."""
    module = make_upgradinatorr(dry_run=False)
    app = _QueuedARR([[_movie(7, tags=["checked"]), _movie(8, tags=["checked"])]])

    result = module.process_instance("radarr", _settings(queue_block_hours=72), app)

    assert result["rotation_done"] is True
    assert (
        'Rotation finished: everything is tagged "checked" and Auto reset processed '
        "tag is off, so nothing is searched until the tag is removed"
    ) in summary_lines(result)


def test_an_empty_library_with_a_waiting_download_is_no_finished_rotation(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _QueuedARR([[]])

    result = module.process_instance("radarr", _settings(queue_block_hours=72), app)

    assert result["rotation_done"] is False


def test_with_auto_reset_on_no_rotation_line_is_shown(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _QueuedARR([[_movie(7, tags=["checked"]), _movie(8, tags=["checked"])]])

    result = module.process_instance(
        "radarr", _settings(queue_block_hours=72, unattended=True), app
    )

    assert result["rotation_done"] is False
    assert not any(line.startswith("Rotation finished") for line in summary_lines(result))


def test_a_fully_tagged_library_warns_with_the_reason(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = FakeARR([[_movie(1, tags=["checked"]), _movie(2, tags=["checked"])]])

    assert module.process_instance("radarr", _settings(), app) is None

    assert module.logger.warnings == [
        'Nothing to search on radarr (2 movies): everything is tagged "checked" and '
        "Auto reset processed tag is off. Remove the tag or turn on Auto reset to "
        "start a new rotation."
    ]


def test_an_empty_library_is_not_reported_as_fully_tagged(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = FakeARR([[]])

    assert module.process_instance("radarr", _settings(), app) is None

    assert module.logger.warnings == ["Nothing to search on radarr: 0 movies found."]


@pytest.mark.parametrize(
    "revision, expected",
    [
        ({"version": 1, "real": 0, "isRepack": False}, "WEBDL-1080p"),
        ({"version": 2, "real": 0, "isRepack": True}, "WEBDL-1080p REPACK"),
        ({"version": 2, "real": 0, "isRepack": False}, "WEBDL-1080p v2"),
        ({"version": 3, "real": 0, "isRepack": True}, "WEBDL-1080p REPACK2"),
        ({"version": 1, "real": 1, "isRepack": False}, "WEBDL-1080p REAL"),
        ({"version": 1, "real": 2, "isRepack": False}, "WEBDL-1080p REAL REAL"),
        ({}, "WEBDL-1080p"),
    ],
)
def test_the_quality_names_its_revision(revision, expected):
    record = {
        "quality": {
            "quality": {"id": 3, "name": "WEBDL-1080p", "source": "web", "resolution": 1080},
            "revision": revision,
        }
    }

    assert Upgradinatorr._quality_name(record) == expected


def test_a_dry_run_lists_what_it_would_search():
    module = make_upgradinatorr(dry_run=True)
    module.logger = _Capture()
    run = Upgradinatorr._new_output(
        SimpleNamespace(instance_name="Radarr", instance_type="Radarr"),
        upgradinatorr_module.GrabReconcile([], set()),
    )
    run["data"] = [{"media_id": 1, "title": "Movie 1", "year": 2001, "grabs": []}]

    module.print_output({"radarr": run})

    assert "[DRY RUN] Would search 1 movie: Movie 1 (2001)" in module.logger.lines
    assert not any("[NO GRABS]" in line for line in module.logger.lines)


def test_a_staged_series_is_not_listed_as_searched_with_nothing_grabbed(isolated_db):
    """Its search is still running on Sonarr and may yet grab."""
    module = make_upgradinatorr(dry_run=False)
    app = _SonarrARR([_series(30, seasons=2), _series(31, seasons=2)], slow={(31, 1)})
    result = module.process_instance("sonarr", _settings(count=2), app)

    module.logger = _Capture()
    module.print_output({"sonarr": result})

    assert summary_lines(result)[0] == (
        "Upgrade search: 2 series searched (3 seasons), 0 grabbed, "
        "1 search staged for the next run"
    )
    assert "[NO GRABS] 1 series searched, nothing grabbed: Show 30 (2006)" in module.logger.lines


def test_a_season_mode_dry_run_names_the_count_not_every_candidate():
    module = make_upgradinatorr(dry_run=True)
    module.logger = _Capture()
    run = Upgradinatorr._new_output(
        SimpleNamespace(instance_name="Sonarr", instance_type="Sonarr"),
        upgradinatorr_module.GrabReconcile([], set()),
    )
    run.update(budget=3, granular=True)
    run["data"] = [
        {"media_id": n, "title": f"Show {n}", "year": 2006, "grabs": []} for n in (1, 2)
    ]

    module.print_output({"sonarr": run})

    assert (
        "[DRY RUN] Would search up to 3 seasons from 2 series: Show 1 (2006), Show 2 (2006)"
        in module.logger.lines
    )


def test_a_finished_rotation_with_only_imports_to_report_still_says_why(
    isolated_db, monkeypatch
):
    module = make_upgradinatorr(dry_run=False)
    imported = {"media_id": 1, "title": "Movie 1", "year": 2001, "replaced": True}
    monkeypatch.setattr(
        module,
        "_collect_completed_imports",
        lambda app, db: upgradinatorr_module.GrabReconcile([imported], {"dl-1"}, 1),
    )
    app = FakeARR([[_movie(1, tags=["checked"]), _movie(2, tags=["checked"])]])

    result = module.process_instance("radarr", _settings(), app)

    assert summary_lines(result) == [
        'Rotation finished: everything is tagged "checked" and Auto reset processed '
        "tag is off, so nothing is searched until the tag is removed",
        "Imported: 1 of 1 grab from earlier runs (1 upgraded)",
    ]


def test_an_empty_wanted_list_is_named_as_the_wanted_list(isolated_db, monkeypatch):
    module = make_upgradinatorr(dry_run=False)
    monkeypatch.setattr(module, "_get_all_wanted", lambda app, mode: [])
    app = FakeARR([[]])
    app.get_all_tags = lambda: []

    assert module.process_instance("radarr", _settings(search_mode="cutoff"), app) is None

    assert module.logger.warnings == ["Nothing to search on radarr: its cutoff list is empty."]


class _BusyARR(FakeARR):
    def count_queued_commands(self, _names):
        return None


class _RunningARR(FakeARR):
    def get_command_state(self, command_id):
        return {"status": "started"}


def _logged_summary(module, result):
    """(log lines, summary lines missing from the log) for one instance."""
    module.logger = _Capture()
    module.print_output({"radarr": result})
    log = module.logger.lines
    return log, [line for line in summary_lines(result) if line not in log]


def test_a_run_that_searched_nothing_still_logs_the_summary(isolated_db):
    """An unreadable command queue stops the searches; the log must still say so."""
    module = make_upgradinatorr(dry_run=False)
    result = module.process_instance("radarr", _settings(), _BusyARR([[_movie(1), _movie(2)]]))

    log, missing = _logged_summary(module, result)

    assert result["data"] == []
    assert missing == [], log
    assert "Upgrade search: nothing searched this run" in log


def test_a_search_still_running_logs_the_waiting_line(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    started = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with ChubDB(logger=StubLogger(), db_path=isolated_db) as db:
        db.upgradinatorr_inflight.stage("radarr", 2, None, 502, "Movie 2 (2001)", started)

    result = module.process_instance("radarr", _settings(), _RunningARR([[_movie(1), _movie(2)]]))
    log, missing = _logged_summary(module, result)

    assert missing == [], log
    assert (
        "Waiting on the last run's search of Movie 2 (2001): nothing new is searched "
        "until it finishes"
    ) in log

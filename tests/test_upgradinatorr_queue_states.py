"""Pins the 2026-08-28 Serum investigation.

Two Serum downloads failed to import on 27 Aug and parked in Lidarr's queue.
Upgradinatorr merged the whole queue into its grab report with no time bound, so
those two dead rows were re-announced as "[GRABBED] ... CF Score: 50" on every
run for the next 30 hours, and the albums kept being searched — which grabbed a
second copy of Jupiter and orphaned the first queue row.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.modules.upgradinatorr import QUEUE_MAX_PAGES, Upgradinatorr
from backend.util.arr import classify_queue_row
from backend.util.notification_formatting import format_for_discord

from tests.test_config import FakeARR, make_upgradinatorr, upgradinatorr_media_item

NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _queue_row(**overrides):
    row = {
        "downloadId": "abc123",
        "artistId": 1066,
        "albumId": 263398,
        "title": "Serum - Jupiter [WEB] [FLAC Lossless]",
        "customFormatScore": 50,
        "status": "completed",
        "trackedDownloadState": "importFailed",
        "trackedDownloadStatus": "warning",
        "added": _iso(NOW - timedelta(hours=30)),
        "statusMessages": [
            {"title": "One or more tracks were not imported", "messages": []},
            {
                "title": "01 - 01 - Jupiter.flac",
                "messages": [
                    "Album match is not close enough: 75.1% vs 80%",
                    "Has missing tracks",
                ],
            },
        ],
    }
    row.update(overrides)
    return row


def test_import_failed_row_classifies_as_stuck():
    assert classify_queue_row(_queue_row()) == "stuck"


def test_in_flight_row_classifies_as_pending():
    row = _queue_row(
        status="downloading", trackedDownloadState="downloading",
        trackedDownloadStatus="ok",
    )
    assert classify_queue_row(row) == "pending"


def test_finished_row_classifies_as_done():
    row = _queue_row(trackedDownloadState="imported", trackedDownloadStatus="ok")
    assert classify_queue_row(row) == "done"


def test_unknown_state_with_warning_still_classifies_as_stuck():
    """Enum-drift guard: the three *arrs don't share a TrackedDownloadState
    vocabulary, so a completed row flagged warning must not read as pending."""
    row = _queue_row(trackedDownloadState="somethingNewInV6")
    assert classify_queue_row(row) == "stuck"


def test_status_messages_flatten_and_dedupe():
    row = _queue_row(
        statusMessages=[
            {"title": "a.flac", "messages": ["Has missing tracks"]},
            {"title": "b.flac", "messages": ["Has missing tracks"]},
            {"title": "Bare title", "messages": []},
        ]
    )
    assert Upgradinatorr._queue_status_messages(row) == [
        "Has missing tracks",
        "Bare title",
    ]


def test_unparseable_added_is_unknown_not_old():
    assert Upgradinatorr._queue_row_age_hours({"added": "not-a-date"}, NOW) is None
    assert Upgradinatorr._queue_row_age_hours({}, NOW) is None


def test_age_is_computed_from_added():
    age = Upgradinatorr._queue_row_age_hours(_queue_row(), NOW)
    assert age == 30.0


def test_blocked_keys_cover_each_arr_id_shape():
    lidarr = Upgradinatorr._queue_record_keys(_queue_row(), "lidarr")
    assert lidarr == [("album", 263398)]

    radarr = Upgradinatorr._queue_record_keys({"movieId": 7}, "radarr")
    assert radarr == [("movie", 7)]

    # Sonarr v5 returns a list; v3/v4 return the scalar. Both must work.
    assert Upgradinatorr._queue_record_keys(
        {"seriesId": 12, "seasonNumbers": [3, 4]}, "sonarr"
    ) == [("season", 12, 3), ("season", 12, 4)]
    assert Upgradinatorr._queue_record_keys(
        {"seriesId": 12, "seasonNumber": 3}, "sonarr"
    ) == [("season", 12, 3)]


def test_blocked_keys_fail_open_when_season_is_unknown():
    """Blocking on incomplete data would stall the rotation silently — worse
    than the duplicate grab the guard exists to prevent."""
    assert Upgradinatorr._queue_record_keys({"seriesId": 12}, "sonarr") == []
    assert Upgradinatorr._queue_record_keys({}, "lidarr") == []


class _StaleQueueARR(FakeARR):
    """A Radarr whose queue holds one import that failed 30 hours ago — the
    shape that produced the phantom '[GRABBED]' lines."""

    def __init__(self, media_batches, added_hours_ago=30):
        super().__init__(media_batches)
        self.added_hours_ago = added_hours_ago
        self.queue_reads = 0

    def get_queue(self, page=1, page_size=200):
        self.queue_reads += 1
        # Relative to the real clock: process_instance stamps its run start with
        # datetime.now(), so a fixed date here would drift as the day passes.
        added = datetime.now(timezone.utc) - timedelta(hours=self.added_hours_ago)
        return {
            "records": [
                _queue_row(
                    downloadId="download-7",
                    movieId=7,
                    albumId=None,
                    title="Movie.2024.1080p.WEB-DL",
                    customFormatScore=7777,
                    added=_iso(added),
                )
            ]
        }


def _settings(**overrides):
    base = dict(
        count=10,
        tag_name="checked",
        ignore_tag="ignore",
        unattended=False,
        season_monitored_threshold=0,
        search_mode="upgrade",
        queue_block_hours=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_stale_queue_row_is_not_reported_as_a_grab():
    module = make_upgradinatorr(dry_run=False)
    app = _StaleQueueARR([[upgradinatorr_media_item([])]])

    result = module.process_instance("radarr", _settings(), app)

    item = result["data"][0]
    assert item["download"] == {}, "a 30h-old queue row is not a grab from this run"
    stuck = [e for e in item["queue_imports"] if e["state"] == "stuck"]
    assert [e["download"] for e in stuck] == ["Movie.2024.1080p.WEB-DL"]
    assert stuck[0]["age_hours"] == pytest.approx(30, abs=0.1)
    assert "Has missing tracks" in stuck[0]["messages"]


def test_queue_row_added_during_the_run_still_counts_as_a_grab():
    module = make_upgradinatorr(dry_run=False)
    # Negative age = queued a moment ago, i.e. by this very run.
    app = _StaleQueueARR([[upgradinatorr_media_item([])]], added_hours_ago=-1)

    result = module.process_instance("radarr", _settings(), app)

    assert result["data"][0]["download"] == {"Movie.2024.1080p.WEB-DL": 7777}
    assert result["data"][0]["queue_imports"] == []


def test_queue_block_skips_the_search_but_still_reports_the_download():
    """The skipped item must stay visible — silently dropping it from the report
    defeats the point of surfacing downloads that never imported."""
    module = make_upgradinatorr(dry_run=False)
    app = _StaleQueueARR([[upgradinatorr_media_item([])]], added_hours_ago=5)

    result = module.process_instance("radarr", _settings(queue_block_hours=72), app)

    assert app.search_calls == [], "already downloaded — must not grab a second copy"
    assert result is not None, "a blocked-only run still has something to report"
    entry = result["data"][0]
    assert entry["download"] == {}
    assert [q["download"] for q in entry["queue_imports"]] == [
        "Movie.2024.1080p.WEB-DL"
    ]


def test_blocked_media_does_not_trigger_the_unattended_tag_reset():
    """An empty candidate list caused by the queue guard is deferred work, not a
    finished rotation — the unattended reset would strip every checked tag."""
    module = make_upgradinatorr(dry_run=False)
    app = _StaleQueueARR([[upgradinatorr_media_item([])]], added_hours_ago=5)

    module.process_instance(
        "radarr", _settings(queue_block_hours=72, unattended=True), app
    )

    assert app.remove_calls == [], "blocked != rotation complete"
    assert app.search_calls == []


class _BadQueueARR(FakeARR):
    """An *arr whose queue endpoint returns something that is not a dict."""

    def __init__(self, media_batches, payload):
        super().__init__(media_batches)
        self.payload = payload

    def get_queue(self, page=1, page_size=200):
        return self.payload


@pytest.mark.parametrize("payload", ["<html>error</html>", [{"a": 1}], 42])
def test_non_dict_queue_response_fails_open_instead_of_crashing(payload):
    module = make_upgradinatorr(dry_run=False)
    app = _BadQueueARR([[upgradinatorr_media_item([])]], payload)

    result = module.process_instance("radarr", _settings(queue_block_hours=72), app)

    assert app.search_calls == [7], "unreadable queue must not block searching"
    assert result is not None


def test_queue_block_expires_so_a_dead_row_cannot_block_forever():
    module = make_upgradinatorr(dry_run=False)
    app = _StaleQueueARR([[upgradinatorr_media_item([])]], added_hours_ago=100)

    module.process_instance("radarr", _settings(queue_block_hours=72), app)

    assert app.search_calls == [7]


def test_notification_splits_grabbed_from_stuck():
    output = {
        "radarr": {
            "server_name": "Radarr",
            "data": [
                {
                    "title": "Serum",
                    "year": None,
                    "download": {"Serum - Jupiter (2019) [single]": 50},
                    "queue_imports": [
                        {
                            "state": "stuck",
                            "download": "Serum - Jupiter [WEB] [FLAC Lossless]",
                            "torrent_custom_format_score": 50,
                            "age_hours": 30.0,
                            "messages": ["Album match is not close enough: 75.1% vs 80%"],
                        }
                    ],
                }
            ],
        }
    }

    fields, ok = format_for_discord(
        SimpleNamespace(module_name="upgradinatorr"), output
    )
    assert ok is True
    rendered = [(f["name"], f["value"]) for page in fields.values() for f in page]
    names = [name for name, _ in rendered]
    body = "\n".join(value for _, value in rendered)

    assert any("import stuck" in name for name in names)
    assert "Serum - Jupiter (2019) [single]" in body
    assert "Album match is not close enough: 75.1% vs 80%" in body


@pytest.mark.parametrize("bad", [1, "oops", {"a": 1}])
def test_malformed_status_messages_do_not_raise(bad):
    """_fetch_queue_records validates only the top-level records, so a junk
    statusMessages value would otherwise abort the whole instance run."""
    assert Upgradinatorr._queue_status_messages(_queue_row(statusMessages=bad)) == []


@pytest.mark.parametrize("bad", [1, "oops"])
def test_malformed_inner_messages_do_not_raise(bad):
    row = _queue_row(statusMessages=[{"title": "a.flac", "messages": bad}])
    assert Upgradinatorr._queue_status_messages(row) == ["a.flac"]


def test_blocked_rows_are_deduplicated_by_download_title():
    """Two queue rows can share a title (a re-grab, or two files of one track);
    the report must not list it twice."""
    out = {"data": []}
    row = {"state": "stuck", "download": "Dupe", "torrent_custom_format_score": 1,
           "age_hours": 5.0, "messages": []}
    Upgradinatorr._append_blocked_rows(
        out, {7: [dict(row), dict(row)]}, [{"media_id": 7, "title": "M", "year": 2024}]
    )
    assert [q["download"] for q in out["data"][0]["queue_imports"]] == ["Dupe"]


def test_dry_run_still_reports_blocked_downloads():
    """A dry run previews what would happen; silently omitting the items the
    queue guard skips makes the preview lie about the run."""
    module = make_upgradinatorr(dry_run=True)
    app = _StaleQueueARR([[upgradinatorr_media_item([])]], added_hours_ago=5)

    result = module.process_instance("radarr", _settings(queue_block_hours=72), app)

    assert app.search_calls == []
    assert [q["download"] for q in result["data"][0]["queue_imports"]] == [
        "Movie.2024.1080p.WEB-DL"
    ]


@pytest.mark.parametrize("bad", [1, "oops", {"a": 1}, None])
def test_as_list_guards_truthy_scalars(bad):
    """`x or []` raises TypeError on a truthy scalar; as_list is the one owner
    of that guard across every *arr response parser."""
    from backend.util.helper import as_list

    assert as_list(bad) == []
    assert as_list([1, 2]) == [1, 2]


@pytest.mark.parametrize("scalar", [3, "3"])
def test_scalar_season_numbers_fails_open(scalar):
    """A scalar seasonNumbers must not raise — that would abort Sonarr queue
    processing rather than leave the series searchable."""
    row = {"seriesId": 12, "seasonNumbers": scalar}
    assert Upgradinatorr._queue_record_keys(row, "sonarr") == []


class _PagedQueueARR(FakeARR):
    """A queue larger than one page. Rows past the first page must still
    suppress, or they get a duplicate search."""

    PAGE = 200

    def __init__(self, media_batches, total):
        super().__init__(media_batches)
        self.total = total
        self.pages_requested = []

    def get_queue(self, page=1, page_size=200):
        self.pages_requested.append(page)
        start = (page - 1) * page_size
        end = min(start + page_size, self.total)
        added = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
        return {
            "records": [
                _queue_row(downloadId=f"d{i}", movieId=7, albumId=None,
                           title=f"Movie.{i}", added=added)
                for i in range(start, max(start, end))
            ]
        }


def test_queue_pagination_covers_rows_past_the_first_page():
    module = make_upgradinatorr(dry_run=False)
    app = _PagedQueueARR([[upgradinatorr_media_item([])]], total=250)

    records = module._fetch_queue_records(app)

    assert len(records) == 250
    assert app.pages_requested[:2] == [1, 2]
    assert records[249]["title"] == "Movie.249"


class _FlakyPagedQueueARR(FakeARR):
    """Page 1 is full, page 2 fails. A partial read must not be used for
    suppression — rows past it would be searched again."""

    def __init__(self, media_batches, page2):
        super().__init__(media_batches)
        self.page2 = page2

    def get_queue(self, page=1, page_size=200):
        if page == 1:
            added = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
            return {
                "records": [
                    _queue_row(downloadId=f"d{i}", movieId=7, albumId=None,
                               title=f"Movie.{i}", added=added)
                    for i in range(page_size)
                ]
            }
        return self.page2


@pytest.mark.parametrize("page2", [None, [], "", 0])
def test_failed_later_page_discards_the_partial_queue_read(page2):
    module = make_upgradinatorr(dry_run=False)
    app = _FlakyPagedQueueARR([[upgradinatorr_media_item([])]], page2)

    assert module._fetch_queue_records(app) is None


def test_genuine_empty_later_page_ends_pagination():
    """A real *arr returns {"records": []} past the end — that is the terminator,
    unlike a failed page."""
    module = make_upgradinatorr(dry_run=False)
    app = _FlakyPagedQueueARR([[upgradinatorr_media_item([])]], {"records": []})

    records = module._fetch_queue_records(app)
    assert records is not None and len(records) == 200


@pytest.mark.parametrize(
    "state", ["failedPending", "downloadFailedPending"]
)
def test_failed_pending_states_classify_as_stuck(state):
    """These are failures en route to Failed, not work in progress — labelling
    them 'awaiting import' tells the user it is still progressing."""
    row = _queue_row(trackedDownloadState=state, trackedDownloadStatus="ok",
                     status="downloading")
    assert classify_queue_row(row) == "stuck"


@pytest.mark.parametrize(
    "stored,expected",
    [
        # unusable -> default, never 0 (0 would silently disable the guard)
        (None, 72), ("", 72), ("   ", 72), ("abc", 72), ({}, 72),
        (-1, 72), ("-5", 72), (0.5, 72), (False, 72), (True, 72),
        # explicit opt-out and real values survive
        (0, 0), ("0", 0), (24, 24), ("24", 24), (24.0, 24),
    ],
)
def test_queue_block_hours_falls_back_without_disabling_the_guard(stored, expected):
    """Only an explicit 0 opts out. A null or blank value reaching `or 0` would
    silently disable queue blocking."""
    module = make_upgradinatorr(dry_run=False)
    assert module._queue_block_hours(SimpleNamespace(queue_block_hours=stored)) == expected


def test_queue_block_hours_defaults_when_absent():
    module = make_upgradinatorr(dry_run=False)
    assert module._queue_block_hours(SimpleNamespace()) == 72


def test_page_cap_discards_the_partial_queue_read():
    """Hitting the page cap is the same situation as a failed page — a partial
    snapshot suppresses only what was read and re-searches the rest."""
    module = make_upgradinatorr(dry_run=False)

    class _EndlessQueueARR(FakeARR):
        def __init__(self):
            super().__init__([[upgradinatorr_media_item([])]])
            self.pages = 0

        def get_queue(self, page=1, page_size=200):
            self.pages += 1
            added = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
            return {
                "records": [
                    _queue_row(downloadId=f"p{page}-{i}", movieId=7, albumId=None,
                               title=f"M.{page}.{i}", added=added)
                    for i in range(page_size)
                ]
            }

    app = _EndlessQueueARR()
    assert module._fetch_queue_records(app) is None
    assert app.pages == QUEUE_MAX_PAGES

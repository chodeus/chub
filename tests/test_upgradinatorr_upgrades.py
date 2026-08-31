"""Pins the completed-upgrade report.

A run ends at the search, so a grab is still downloading when the notification
is built — announcing it as an upgrade was announcing an intention. Upgrades are
now confirmed on a LATER run: the grab's download imported AND an existing file
was deleted "for Upgrade". Missing-mode backfill replaces nothing, so it drops
out without the run needing to know its search_mode.
"""

from types import SimpleNamespace

import pytest

import backend.modules.upgradinatorr as upgradinatorr_module
from backend.util.database.upgradinatorr_grabs import UpgradinatorrGrabs

from tests.test_config import (
    FakeARR,
    StubLogger,
    make_upgradinatorr,
    upgradinatorr_media_item,
)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """process_instance opens its own ChubDB — keep it out of config/chub.db,
    or grabs leak between tests."""
    path = str(tmp_path / "chub.db")
    real = upgradinatorr_module.ChubDB
    monkeypatch.setattr(
        upgradinatorr_module, "ChubDB", lambda **kwargs: real(db_path=path, **kwargs)
    )
    return path


class _FakeGrabs:
    """Stands in for the UpgradinatorrGrabs table."""

    def __init__(self, pending_rows):
        self.rows = list(pending_rows)
        self.cleared = []
        self.pruned = []

    def prune(self, instance_name, days):
        self.pruned.append((instance_name, days))

    def pending(self, instance_name):
        return list(self.rows)

    def clear(self, instance_name, download_ids):
        self.cleared.extend(download_ids)

    def record(self, instance_name, grabs, grabbed_at=None):
        self.rows.extend(grabs)


class _HistoryARR(FakeARR):
    """A client whose history is scripted per event type."""

    history_import_event = 3
    history_upgrade_delete_event = 6
    upgrade_pair_field = "movieId"

    def __init__(self, imports, deletes, media=None):
        super().__init__([[upgradinatorr_media_item([])] if media is None else media])
        self._by_event = {3: imports, 6: deletes}
        self.since_calls = []

    def get_history_since(self, date, event_type):
        self.since_calls.append((date, event_type))
        return self._by_event.get(event_type)


def _collect(module, app, grabs):
    """The collector returns (upgrades, resolved ids); most tests want the first."""
    upgrades, _resolved = module._collect_completed_upgrades(app, grabs)
    return upgrades


def _grab(download_id="dl-1", **overrides):
    row = {
        "download_id": download_id,
        "media_id": 7,
        "title": "Movie",
        "year": 2024,
        "release_title": "Movie.2024.REMUX-GRP",
        "score": 4000,
        "grabbed_at": "2026-08-29T09:00:00+00:00",
    }
    row.update(overrides)
    return row


def _import(
    download_id="dl-1",
    movie_id=7,
    score=7007,
    date="2026-08-29T10:00:01Z",
    quality="WEBDL-1080p",
):
    return {
        "downloadId": download_id,
        "movieId": movie_id,
        "customFormatScore": score,
        "date": date,
        "quality": {"quality": {"name": quality}},
    }


def _delete(
    movie_id=7,
    score=4851,
    reason="Upgrade",
    date="2026-08-29T10:00:00Z",
    quality="WEBDL-1080p",
):
    return {
        "movieId": movie_id,
        "customFormatScore": score,
        "data": {"reason": reason},
        "date": date,
        "quality": {"quality": {"name": quality}},
    }


def test_import_that_replaced_a_file_is_reported_with_both_scores():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [_delete()])

    upgrades, resolved = module._collect_completed_upgrades(app, grabs)

    assert resolved == {"dl-1"}
    assert upgrades == [
        {
            "media_id": 7,
            "title": "Movie",
            "year": 2024,
            "download": "Movie.2024.REMUX-GRP",
            "score": 7007,
            "previous_score": 4851,
            "quality": "WEBDL-1080p",
            "previous_quality": "WEBDL-1080p",
        }
    ]


def test_import_that_replaced_nothing_is_not_an_upgrade():
    """Lidarr's missing-mode backfill: the album imported, but no file was
    deleted for Upgrade, so there is nothing to announce."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [])

    upgrades, resolved = module._collect_completed_upgrades(app, grabs)

    assert upgrades == []
    # The outcome IS known — it just wasn't an upgrade — so the grab is settled.
    assert resolved == {"dl-1"}


def test_delete_for_another_reason_is_not_an_upgrade():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [_delete(reason="Manual")])

    upgrades = _collect(module, app, grabs)

    assert upgrades == []


def test_upgrade_of_a_different_item_does_not_credit_our_grab():
    """The delete must be for the media our grab imported into."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import(movie_id=7)], [_delete(movie_id=99)])

    upgrades = _collect(module, app, grabs)

    assert upgrades == []


def test_an_unrelated_import_is_ignored():
    """History is instance-wide: an upgrade this module did not cause (RSS, a
    manual search) must not appear under an Upgradinatorr heading."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(download_id="ours")])
    app = _HistoryARR([_import(download_id="someone-elses")], [_delete()])

    upgrades, resolved = module._collect_completed_upgrades(app, grabs)

    assert upgrades == []
    assert resolved == set()


def test_season_pack_reports_once_not_once_per_episode():
    """Sonarr lands one import record per episode under a single downloadId."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(score=7007), _import(score=7007), _import(score=7007)],
        [_delete()],
    )

    upgrades = _collect(module, app, grabs)

    assert len(upgrades) == 1


def test_unreadable_history_fails_closed_and_keeps_the_grab_pending():
    """A failed read is not evidence that nothing upgraded — dropping the grab
    would lose the upgrade permanently."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(None, [_delete()])

    upgrades, resolved = module._collect_completed_upgrades(app, grabs)

    assert upgrades == []
    assert resolved == set()


def test_no_pending_grabs_makes_no_history_call():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([])
    app = _HistoryARR([_import()], [_delete()])

    upgrades = _collect(module, app, grabs)

    assert upgrades == []
    assert app.since_calls == []


def test_lookback_starts_at_the_oldest_pending_grab():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs(
        [
            _grab(download_id="new", grabbed_at="2026-08-29T09:00:00+00:00"),
            _grab(download_id="old", grabbed_at="2026-08-24T01:30:00+00:00"),
        ]
    )
    app = _HistoryARR([], [])

    _collect(module, app, grabs)

    assert [date for date, _event in app.since_calls] == [
        "2026-08-24T01:30:00Z",
        "2026-08-24T01:30:00Z",
    ]


def test_client_without_an_event_mapping_reports_nothing():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = SimpleNamespace(instance_name="radarr")

    upgrades = _collect(module, app, grabs)

    assert upgrades == []


def test_pending_grabs_survive_a_round_trip(tmp_path):
    db = UpgradinatorrGrabs(StubLogger(), db_path=str(tmp_path / "grabs.db"))
    db.record("radarr", [_grab()], grabbed_at="2026-08-29T09:00:00+00:00")
    # A re-run re-reporting the same download must not duplicate the row.
    db.record("radarr", [_grab()], grabbed_at="2026-08-30T09:00:00+00:00")

    rows = db.pending("radarr")
    assert len(rows) == 1
    assert rows[0]["download_id"] == "dl-1"
    assert rows[0]["release_title"] == "Movie.2024.REMUX-GRP"
    assert rows[0]["grabbed_at"] == "2026-08-29T09:00:00+00:00"
    oldest = db.oldest_pending("radarr")
    assert oldest == "2026-08-29T09:00:00+00:00"

    db.clear("radarr", ["dl-1"])
    pending = db.pending("radarr")
    assert pending == []


def test_prune_drops_grabs_past_the_retention_window(tmp_path):
    db = UpgradinatorrGrabs(StubLogger(), db_path=str(tmp_path / "grabs.db"))
    db.record(
        "radarr", [_grab(download_id="stale")], grabbed_at="2020-01-01T00:00:00+00:00"
    )
    db.record("radarr", [_grab(download_id="fresh")])

    db.prune("radarr", upgradinatorr_module.GRAB_RETENTION_DAYS)

    remaining = db.pending("radarr")
    assert [row["download_id"] for row in remaining] == ["fresh"]


def test_grabs_are_scoped_per_instance(tmp_path):
    db = UpgradinatorrGrabs(StubLogger(), db_path=str(tmp_path / "grabs.db"))
    db.record("radarr", [_grab()])
    db.record("radarr4k", [_grab()])

    radarr_rows = db.pending("radarr")
    assert len(radarr_rows) == 1
    db.clear("radarr", ["dl-1"])
    radarr4k_rows = db.pending("radarr4k")
    assert len(radarr4k_rows) == 1


class _DedupeARR(FakeARR):
    """Grab history and a queue row that name the same download differently —
    exactly what Lidarr does (its queue drops the year and reorders tags)."""

    history_import_event = 3
    history_upgrade_delete_event = 6
    upgrade_pair_field = "movieId"

    def __init__(self, grab_history, queue_rows):
        super().__init__([[upgradinatorr_media_item([])]])
        self._grab_history = grab_history
        self._queue_rows = queue_rows
        self._history_calls = 0
        self.recorded = []

    def get_grab_history(self, media_id):
        # First call is the "before" snapshot; the grab appears only after.
        self._history_calls += 1
        return [] if self._history_calls == 1 else self._grab_history

    def get_queue(self, page=1, page_size=200):
        return {"records": self._queue_rows}

    def get_history_since(self, date, event_type):
        return []


def _upgrade_settings(**overrides):
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


def test_a_queue_row_is_not_a_second_grab_when_only_the_title_differs(isolated_db):
    """The Lidarr double-listing: 7 rows for 4 albums, because the queue title
    never string-matches the grab-history sourceTitle."""
    module = make_upgradinatorr(dry_run=False)
    app = _DedupeARR(
        grab_history=[
            {
                "downloadId": "dl-1",
                "movieId": 7,
                "sourceTitle": "Movie - Like You (2022) [single] [FLAC 24bit 96kHz] [WEB]",
                "customFormatScore": 55,
                "eventType": "grabbed",
            }
        ],
        queue_rows=[
            {
                "downloadId": "dl-1",
                "movieId": 7,
                "title": "Movie - Like You [WEB] [FLAC 24bit 96kHz]",
                "customFormatScore": 55,
                "status": "downloading",
                "trackedDownloadState": "downloading",
            }
        ],
    )

    result = module.process_instance("radarr", _upgrade_settings(), app)

    downloads = result["data"][0]["grabs"]
    assert len(downloads) == 1, f"same download listed twice: {downloads}"


def test_synthetic_download_ids_are_never_stored(isolated_db):
    """_history_record_to_download mints "history:<id>" when an *arr reports no
    downloadId; such a row can never match an import and would pin the lookback."""
    module = make_upgradinatorr(dry_run=False)
    app = _DedupeARR(
        grab_history=[
            {
                "downloadId": None,
                "id": 51,
                "movieId": 7,
                "sourceTitle": "Movie.2024.REMUX-GRP",
                "customFormatScore": 7007,
                "eventType": "grabbed",
            }
        ],
        queue_rows=[],
    )

    result = module.process_instance("radarr", _upgrade_settings(), app)

    assert [g["download"] for g in result["data"][0]["grabs"]] == [
        "Movie.2024.REMUX-GRP"
    ]
    stored = UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).pending("radarr")
    assert stored == []


def test_a_real_download_id_is_stored_for_the_next_run(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _DedupeARR(
        grab_history=[
            {
                "downloadId": "dl-1",
                "movieId": 7,
                "sourceTitle": "Movie.2024.REMUX-GRP",
                "customFormatScore": 7007,
                "eventType": "grabbed",
            }
        ],
        queue_rows=[],
    )

    module.process_instance("radarr", _upgrade_settings(), app)

    rows = UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).pending("radarr")
    assert [row["download_id"] for row in rows] == ["dl-1"]
    assert rows[0]["release_title"] == "Movie.2024.REMUX-GRP"


def test_an_import_that_was_itself_replaced_later_is_not_an_upgrade():
    """Lioness S03E05: playWEB imported, then NTb imported hours later and
    deleted playWEB's file. One delete, two imports — crediting both reported
    the replaced release as an upgrade, and "(was 3525)" against its own score.
    """
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(download_id="playweb"), _grab(download_id="ntb")])
    app = _HistoryARR(
        [
            _import(download_id="playweb", score=3525, date="2026-08-29T01:14:02Z"),
            _import(download_id="ntb", score=3575, date="2026-08-29T11:20:31Z"),
        ],
        [_delete(score=3525, date="2026-08-29T11:20:30Z")],
    )

    upgrades, resolved = module._collect_completed_upgrades(app, grabs)

    assert [upgrade["score"] for upgrade in upgrades] == [3575]
    assert upgrades[0]["previous_score"] == 3525
    # Both imports resolved — one as an upgrade, one as a plain import.
    assert resolved == {"ntb", "playweb"}


def test_a_delete_outside_the_pairing_window_is_not_this_import():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(date="2026-08-29T10:00:00Z")],
        [_delete(date="2026-08-29T14:00:00Z")],
    )

    upgrades = _collect(module, app, grabs)

    assert upgrades == []


def test_the_closest_import_claims_the_delete_not_the_earliest():
    """Dark Matter S02E01: NTb imported at :00, FLUX at :01, one delete at :01.
    Matching in time order handed the delete to NTb — the release FLUX replaced.
    """
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(download_id="ntb"), _grab(download_id="flux")])
    app = _HistoryARR(
        [
            _import(download_id="ntb", score=3575, date="2026-08-28T04:33:00Z"),
            _import(download_id="flux", score=4876, date="2026-08-28T04:33:01Z"),
        ],
        [_delete(score=4825, date="2026-08-28T04:33:01Z")],
    )

    upgrades = _collect(module, app, grabs)

    assert [upgrade["score"] for upgrade in upgrades] == [4876]
    assert upgrades[0]["previous_score"] == 4825


def test_a_quality_gain_is_shown_when_the_cf_score_fell():
    """Measured on a live library: every upgrade whose CF score went DOWN was a
    quality gain, which outranks custom formats. Without the quality line the
    notification reads as a downgrade."""
    from types import SimpleNamespace

    from backend.util.notification_formatting import format_for_discord

    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(score=2550, quality="Remux-1080p")],
        [_delete(score=5570, quality="WEBDL-1080p")],
    )

    upgrades = _collect(module, app, grabs)
    assert upgrades[0]["quality"] == "Remux-1080p"
    assert upgrades[0]["previous_quality"] == "WEBDL-1080p"

    fields, ok = format_for_discord(
        SimpleNamespace(module_name="upgradinatorr"),
        {"radarr": {"server_name": "Radarr", "data": [], "upgrades": upgrades}},
    )
    body = "\n".join(f["value"] for page in fields.values() for f in page)
    assert "Quality: WEBDL-1080p → Remux-1080p" in body
    assert "CF Score: 2550 (was 5570)" in body


def test_no_quality_line_when_the_quality_did_not_move():
    from types import SimpleNamespace

    from backend.util.notification_formatting import format_for_discord

    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [_delete()])

    fields, ok = format_for_discord(
        SimpleNamespace(module_name="upgradinatorr"),
        {
            "radarr": {
                "server_name": "Radarr",
                "data": [],
                "upgrades": _collect(module, app, grabs),
            }
        },
    )
    body = "\n".join(f["value"] for page in fields.values() for f in page)
    assert "Quality:" not in body
    assert "CF Score: 7007 (was 4851)" in body


def test_two_downloads_sharing_a_release_title_both_count(isolated_db):
    """The parent's grab list was keyed by title, so two distinct downloads
    named identically collapsed into one — the [GRABBED] tally then undercounted
    what was actually grabbed and persisted."""
    module = make_upgradinatorr(dry_run=False)
    app = _DedupeARR(
        grab_history=[
            {
                "downloadId": "dl-1",
                "movieId": 7,
                "sourceTitle": "Movie.2024.REMUX-GRP",
                "customFormatScore": 7007,
                "eventType": "grabbed",
            },
            {
                "downloadId": "dl-2",
                "movieId": 7,
                "sourceTitle": "Movie.2024.REMUX-GRP",
                "customFormatScore": 7007,
                "eventType": "grabbed",
            },
        ],
        queue_rows=[],
    )

    result = module.process_instance("radarr", _upgrade_settings(), app)

    grabs = result["data"][0]["grabs"]
    assert [grab["download_id"] for grab in grabs] == ["dl-1", "dl-2"]
    # What the log counts and what the next run can resolve must agree.
    stored = UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).pending("radarr")
    assert len(stored) == len(grabs)


def test_upgrades_survive_the_nothing_left_to_search_bail_out(isolated_db):
    """process_instance bails out early when there is no media to search. The
    collector has already cleared those grabs from the table, so returning None
    there loses a completed upgrade permanently rather than deferring it."""
    module = make_upgradinatorr(dry_run=False)
    UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).record(
        "radarr", [_grab()], grabbed_at="2026-08-29T09:00:00+00:00"
    )
    app = _HistoryARR([_import()], [_delete()], media=[])

    result = module.process_instance("radarr", _upgrade_settings(unattended=False), app)

    assert result is not None, "the bail-out dropped a completed upgrade"
    assert [upgrade["download"] for upgrade in result["upgrades"]] == [
        "Movie.2024.REMUX-GRP"
    ]


def test_nothing_to_search_and_no_upgrades_still_reports_nothing(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _HistoryARR([], [], media=[])

    result = module.process_instance("radarr", _upgrade_settings(unattended=False), app)

    assert result is None


def test_a_broken_history_read_does_not_stop_the_searches(isolated_db):
    """The reconcile now runs upstream of the searches, so an *arr that throws
    on /history must not cost the run its whole search budget."""

    class _ExplodingARR(_HistoryARR):
        def get_history_since(self, date, event_type):
            raise RuntimeError("boom")

    module = make_upgradinatorr(dry_run=False)
    UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).record(
        "radarr", [_grab()], grabbed_at="2026-08-29T09:00:00+00:00"
    )
    app = _ExplodingARR([], [])

    result = module.process_instance("radarr", _upgrade_settings(), app)

    assert app.search_calls == [7], "a reporting failure skipped the searches"
    assert result is not None
    assert result["upgrades"] == []


def test_a_run_that_aborts_after_the_reconcile_keeps_the_grab(isolated_db):
    """The reconcile runs before get_all_media(). If that throws, the worker
    discards the instance result — so clearing the grab at reconcile time lost
    the upgrade for good instead of retrying it next run."""

    class _FailsAfterReconcileARR(_HistoryARR):
        def get_all_media(self, *args, **kwargs):
            raise RuntimeError("arr went away")

    db = UpgradinatorrGrabs(StubLogger(), db_path=isolated_db)
    db.record("radarr", [_grab()], grabbed_at="2026-08-29T09:00:00+00:00")
    module = make_upgradinatorr(dry_run=False)
    app = _FailsAfterReconcileARR([_import()], [_delete()])

    with pytest.raises(RuntimeError):
        module.process_instance("radarr", _upgrade_settings(), app)

    pending = db.pending("radarr")
    assert [row["download_id"] for row in pending] == ["dl-1"], (
        "an aborted run must leave the grab for the next one"
    )


def test_the_report_is_settled_only_once_it_has_been_written(isolated_db):
    """print_output writes the run log — this module's durable handoff — well
    after process_instance returns. Settling before that can drop an upgrade
    that was never reported anywhere, so the result carries the ids instead."""
    db = UpgradinatorrGrabs(StubLogger(), db_path=isolated_db)
    db.record("radarr", [_grab()], grabbed_at="2026-08-29T09:00:00+00:00")
    module = make_upgradinatorr(dry_run=False)
    app = _HistoryARR([_import()], [_delete()], media=[])

    result = module.process_instance("radarr", _upgrade_settings(unattended=False), app)

    assert result["upgrades"][0]["download"] == "Movie.2024.REMUX-GRP"
    assert result["resolved_grabs"] == ["dl-1"]
    still_pending = db.pending("radarr")
    assert still_pending, "settled before the report was written"

    module.print_output({"radarr": result})
    module._settle_reported_grabs({"radarr": result})

    settled = db.pending("radarr")
    assert settled == []
    # Popped on the way out, so it can never reach a notification payload.
    assert "resolved_grabs" not in result

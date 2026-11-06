"""Pins the completed-import report: an import that deleted a file "for Upgrade"
is an upgrade, one that replaced nothing is a first acquisition. Both report."""

from datetime import datetime, timedelta, timezone
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
    history_failed_event = 4
    upgrade_pair_field = "movieId"

    def __init__(self, imports, deletes, media=None, failures=()):
        super().__init__([[upgradinatorr_media_item([])] if media is None else media])
        self._by_event = {
            self.history_import_event: imports,
            self.history_upgrade_delete_event: deletes,
            self.history_failed_event: list(failures),
        }
        self.since_calls = []

    def get_history_since(self, date, event_type):
        self.since_calls.append((date, event_type))
        return self._by_event.get(event_type)


def _collect(module, app, grabs):
    """The completed rows of one reconcile; most tests want only those."""
    return module._collect_completed_imports(app, grabs).completed


def _pending_since(hours: float = 1.0) -> str:
    """A grab stamp inside GRAB_RETENTION_DAYS."""
    # Must stay relative — a fixed date ages out and the reconcile's prune()
    # empties the table before the assertion runs.
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _grab(download_id="dl-1", **overrides):
    row = {
        "download_id": download_id,
        "media_id": 7,
        "title": "Movie",
        "year": 2024,
        "release_title": "Movie.2024.REMUX-GRP",
        "score": 4000,
        "grabbed_at": _pending_since(),
    }
    row.update(overrides)
    return row


def _import(
    download_id="dl-1",
    movie_id=7,
    score=7007,
    date="2026-08-29T10:00:01Z",
    quality="WEBDL-1080p",
    formats=None,
):
    row = {
        "downloadId": download_id,
        "movieId": movie_id,
        "customFormatScore": score,
        "date": date,
        "quality": {"quality": {"name": quality}},
    }
    if formats is not None:
        row["customFormats"] = [{"id": i, "name": n} for i, n in enumerate(formats)]
    return row


def _delete(
    movie_id=7,
    score=4851,
    reason="Upgrade",
    date="2026-08-29T10:00:00Z",
    quality="WEBDL-1080p",
    formats=None,
):
    row = {
        "movieId": movie_id,
        "customFormatScore": score,
        "data": {"reason": reason},
        "date": date,
        "quality": {"quality": {"name": quality}},
    }
    if formats is not None:
        row["customFormats"] = [{"id": i, "name": n} for i, n in enumerate(formats)]
    return row


def test_import_that_replaced_a_file_is_reported_with_both_scores():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(formats=["x264", "BHDStudio", "aac", "1080p", "bluray tier 01"])],
        [_delete(formats=["x264", "AMZN"])],
    )

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, pending = seen.completed, seen.resolved, seen.pending

    assert resolved == {"dl-1"}
    assert pending == 1
    assert completed == [
        {
            "media_id": 7,
            "title": "Movie",
            "year": 2024,
            "download": "Movie.2024.REMUX-GRP",
            "score": 7007,
            "previous_score": 4851,
            "quality": "WEBDL-1080p",
            "previous_quality": "WEBDL-1080p",
            "custom_formats": ["1080p", "aac", "BHDStudio", "bluray tier 01", "x264"],
            "previous_custom_formats": ["AMZN", "x264"],
            "replaced": True,
        }
    ]


def test_import_that_replaced_nothing_is_an_acquisition():
    """Missing-mode backfill: the album imported having replaced no file, which
    reporting only replacements dropped from the notification."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [])

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    assert [(it["download"], it["replaced"]) for it in completed] == [
        ("Movie.2024.REMUX-GRP", False)
    ]
    # Nothing was replaced, so there is no outgoing file to name.
    assert completed[0]["previous_score"] is None
    assert completed[0]["previous_quality"] is None
    assert completed[0]["previous_custom_formats"] is None
    # An *arr that sends no customFormats list is unknown, not "no formats".
    assert completed[0]["custom_formats"] is None
    assert resolved == {"dl-1"}


def test_delete_for_another_reason_is_not_an_upgrade():
    """A file the user deleted by hand is not what this import replaced."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [_delete(reason="Manual")])

    completed = _collect(module, app, grabs)

    assert [it["replaced"] for it in completed] == [False]
    assert completed[0]["previous_score"] is None


def test_upgrade_of_a_different_item_does_not_credit_our_grab():
    """The delete must be for the media our grab imported into — crediting it
    would print "(was 4851)" against a file this release never replaced."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import(movie_id=7)], [_delete(movie_id=99)])

    completed = _collect(module, app, grabs)

    assert [it["replaced"] for it in completed] == [False]
    assert completed[0]["previous_score"] is None


def test_an_unrelated_import_is_ignored():
    """History is instance-wide: an upgrade this module did not cause (RSS, a
    manual search) must not appear under an Upgradinatorr heading."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(download_id="ours")])
    app = _HistoryARR([_import(download_id="someone-elses")], [_delete()])

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    assert completed == []
    assert resolved == set()


def test_season_pack_reports_once_not_once_per_episode():
    """Sonarr lands one import record per episode under a single downloadId."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(score=7007), _import(score=7007), _import(score=7007)],
        [_delete()],
    )

    completed = _collect(module, app, grabs)

    assert len(completed) == 1


def test_a_pack_that_replaced_one_file_is_an_upgrade_not_an_acquisition():
    """A pack imports one record per episode under one downloadId and only some
    replace a file; the paired record must win the dedupe, not the earliest."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [
            _import(score=3000, date="2026-08-29T10:00:00Z"),
            _import(score=7007, date="2026-08-29T12:00:00Z"),
        ],
        [_delete(score=4851, date="2026-08-29T12:00:01Z")],
    )

    completed = _collect(module, app, grabs)

    assert [(it["score"], it["replaced"]) for it in completed] == [(7007, True)]
    assert completed[0]["previous_score"] == 4851


def test_unreadable_history_fails_closed_and_keeps_the_grab_pending():
    """A failed read is not evidence that nothing upgraded — dropping the grab
    would lose the upgrade permanently."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(None, [_delete()])

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    assert completed == []
    assert resolved == set()


def test_an_unreadable_delete_history_keeps_the_grab_pending():
    """The deletes side is what says an import REPLACED something. Trusting a
    failed read there would report every real upgrade as a first acquisition.
    """
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], None)

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    assert completed == []
    assert resolved == set()


def test_a_paged_delete_envelope_is_not_read_as_zero_deletes():
    """The dangerous shape is truthy but wrong: iterating a paged envelope walks
    its KEYS, finds no delete, and silently files every upgrade as acquired."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], {"records": [_delete()]})

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    assert completed == []
    assert resolved == set()


def test_no_pending_grabs_makes_no_history_call():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([])
    app = _HistoryARR([_import()], [_delete()])

    completed = _collect(module, app, grabs)

    assert completed == []
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

    # Imports, upgrade deletes and failed downloads all read from the same start.
    assert app.since_calls == [
        ("2026-08-24T01:30:00Z", 3),
        ("2026-08-24T01:30:00Z", 6),
        ("2026-08-24T01:30:00Z", 4),
    ]


def test_client_without_an_event_mapping_reports_nothing():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = SimpleNamespace(instance_name="radarr")

    completed = _collect(module, app, grabs)

    assert completed == []


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


def test_a_fixture_grab_survives_the_retention_prune(tmp_path):
    """Every isolated_db test reconciles through prune() first, so a grab stamp
    that ages out of GRAB_RETENTION_DAYS empties the table before the assertion."""
    db = UpgradinatorrGrabs(StubLogger(), db_path=str(tmp_path / "grabs.db"))
    db.record("radarr", [_grab()], grabbed_at=_pending_since())

    db.prune("radarr", upgradinatorr_module.GRAB_RETENTION_DAYS)

    assert [row["download_id"] for row in db.pending("radarr")] == ["dl-1"]


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

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    upgraded = [it for it in completed if it["replaced"]]
    assert [it["score"] for it in upgraded] == [3575]
    assert upgraded[0]["previous_score"] == 3525
    # playWEB still imported, so it is reported — as an acquisition, never with
    # "(was 3525)" against its own score.
    acquired = [it for it in completed if not it["replaced"]]
    assert [it["score"] for it in acquired] == [3525]
    assert acquired[0]["previous_score"] is None
    assert resolved == {"ntb", "playweb"}


def test_a_delete_outside_the_pairing_window_is_not_this_import():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(date="2026-08-29T10:00:00Z")],
        [_delete(date="2026-08-29T14:00:00Z")],
    )

    completed = _collect(module, app, grabs)

    assert [it["replaced"] for it in completed] == [False]
    assert completed[0]["previous_score"] is None


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

    completed = _collect(module, app, grabs)

    upgraded = [it for it in completed if it["replaced"]]
    assert [it["score"] for it in upgraded] == [4876]
    assert upgraded[0]["previous_score"] == 4825


def test_a_quality_gain_is_shown_when_the_cf_score_fell():
    """Measured on a live library: every upgrade whose CF score went DOWN was a
    quality gain, which outranks custom formats. Without the quality line the
    notification reads as a downgrade."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(score=2550, quality="Remux-1080p")],
        [_delete(score=5570, quality="WEBDL-1080p")],
    )

    completed = _collect(module, app, grabs)
    assert completed[0]["quality"] == "Remux-1080p"
    assert completed[0]["previous_quality"] == "WEBDL-1080p"

    body = _embed_body(completed)
    assert "- WEBDL-1080p\n- Score: 5570\n+ Remux-1080p\n+ Score: 2550" in body


def test_an_upgrade_diffs_both_files_even_when_the_quality_held():
    """The diff states each side whole, so an unmoved quality still shows on both."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR(
        [_import(formats=["DTS-HD MA", "BHDStudio"])],
        [_delete(formats=["DTS"])],
    )

    body = _embed_body(_collect(module, app, grabs))
    assert "Movie (2024) — upgraded" in body
    assert "Release: Movie.2024.REMUX-GRP" in body
    assert (
        "```diff\n- WEBDL-1080p\n- CF: DTS\n- Score: 4851\n"
        "+ WEBDL-1080p\n+ CF: BHDStudio, DTS-HD MA\n+ Score: 7007\n```"
    ) in body


def _run_log(module, completed):
    """print_output's lines for one instance holding these completed imports."""
    return _run_log_output(
        module,
        upgradinatorr_module.Upgradinatorr._new_output(
            "Radarr", upgradinatorr_module.GrabReconcile(completed, set())
        ),
    )


def _embed_body(completed):
    """Every description, field name and value the notification would send."""
    from backend.util.notification_formatting import format_for_discord

    parts, ok = format_for_discord(
        SimpleNamespace(module_name="upgradinatorr"),
        {"radarr": {"server_name": "Radarr", "data": [], "completed": completed}},
    )
    assert ok
    text = [part.get("description") or "" for part in parts]
    text += [f"{f['name']}\n{f['value']}" for part in parts for f in part["fields"]]
    return "\n".join(text)


def test_an_acquisition_names_the_quality_it_got():
    """An acquisition replaced nothing, so there is no transition to show — but
    the quality obtained is the one fact worth stating about a new file."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import(quality="FLAC")], [])

    completed = _collect(module, app, grabs)

    assert completed[0]["replaced"] is False
    log = _run_log(module, completed)
    body = _embed_body(completed)
    assert "Movie (2024) — acquired" in body
    assert "```diff\n+ FLAC\n+ Score: 7007\n```" in body
    assert "\n- " not in body
    assert "Score 7007, FLAC —" in log


def test_an_unknown_score_prints_no_score_at_all():
    """The *arr reported no customFormatScore and the grab stored none either.
    Rendering it printed a literal "Score None" / "CF Score: None"."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(score=None)])
    app = _HistoryARR([_import(score=None, quality="FLAC")], [])

    completed = _collect(module, app, grabs)
    assert completed[0]["score"] is None

    body = _embed_body(completed)
    assert "None" not in body
    assert "Score" not in body
    assert "+ FLAC" in body
    log = _run_log(module, completed)
    assert "None" not in log
    assert "FLAC — Movie.2024.REMUX-GRP" in log


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


def test_a_searched_run_carries_what_the_notification_summary_reads(isolated_db):
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

    result = module.process_instance("radarr", _upgrade_settings(count=3), app)

    summary_keys = (
        "instance_type",
        "search_mode",
        "budget",
        "granular",
        "tagged_count",
        "tagged_in_run",
        "total_count",
        "searches_attempted",
        "pending_grabs",
    )
    assert {key: result[key] for key in summary_keys} == {
        "instance_type": "radarr",
        "search_mode": "upgrade",
        "budget": 3,
        "granular": False,
        "tagged_count": 0,
        "tagged_in_run": 1,
        "total_count": 1,
        "searches_attempted": 1,
        "pending_grabs": 0,
    }


def test_upgrades_survive_the_nothing_left_to_search_bail_out(isolated_db):
    """process_instance bails out early when there is no media to search, so
    returning None there would drop an import the reconcile already confirmed."""
    module = make_upgradinatorr(dry_run=False)
    UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).record(
        "radarr", [_grab()], grabbed_at=_pending_since()
    )
    app = _HistoryARR([_import()], [_delete()], media=[])

    result = module.process_instance("radarr", _upgrade_settings(unattended=False), app)

    assert result is not None, "the bail-out dropped a completed upgrade"
    assert [it["download"] for it in result["completed"]] == ["Movie.2024.REMUX-GRP"]
    assert result["pending_grabs"] == 1
    # No search ran, so the notification must not print a search or progress line.
    assert "budget" not in result


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
        "radarr", [_grab()], grabbed_at=_pending_since()
    )
    app = _ExplodingARR([], [])

    result = module.process_instance("radarr", _upgrade_settings(), app)

    assert app.search_calls == [7], "a reporting failure skipped the searches"
    assert result is not None
    assert result["completed"] == []


def test_a_run_that_aborts_after_the_reconcile_keeps_the_grab(isolated_db):
    """The reconcile runs before get_all_media(). If that throws, the worker
    discards the instance result — so clearing the grab at reconcile time lost
    the upgrade for good instead of retrying it next run."""

    class _FailsAfterReconcileARR(_HistoryARR):
        def get_all_media(self, *args, **kwargs):
            raise RuntimeError("arr went away")

    db = UpgradinatorrGrabs(StubLogger(), db_path=isolated_db)
    db.record("radarr", [_grab()], grabbed_at=_pending_since())
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
    db.record("radarr", [_grab()], grabbed_at=_pending_since())
    module = make_upgradinatorr(dry_run=False)
    app = _HistoryARR([_import()], [_delete()], media=[])

    result = module.process_instance("radarr", _upgrade_settings(unattended=False), app)

    assert result["completed"][0]["download"] == "Movie.2024.REMUX-GRP"
    assert result["resolved_grabs"] == ["dl-1"]
    still_pending = db.pending("radarr")
    assert still_pending, "settled before the report was written"

    module.print_output({"radarr": result})
    module._settle_reported_grabs({"radarr": result})

    settled = db.pending("radarr")
    assert settled == []
    # Popped on the way out, so it can never reach a notification payload.
    assert "resolved_grabs" not in result


class _LidarrHistoryARR(_HistoryARR):
    """Lidarr pairs by album and can look albums up by id."""

    history_import_event = 8
    history_upgrade_delete_event = 5
    history_failed_event = 4
    upgrade_pair_field = "albumId"

    def __init__(self, imports, deletes, albums):
        super().__init__(imports, deletes)
        self._albums = albums
        self.album_lookups = []

    def get_albums_by_id(self, album_ids):
        self.album_lookups.append(list(album_ids))
        if isinstance(self._albums, Exception):
            raise self._albums
        return self._albums


def _lidarr_import(**overrides):
    row = _import(**overrides)
    row.pop("movieId")
    row["albumId"] = 31
    return row


def _lidarr_delete():
    row = _delete()
    row.pop("movieId")
    row["albumId"] = 31
    return row


_FAVELA = {
    "id": 31,
    "title": "Favela on Blast: Rio Baile Funk 04",
    "albumType": "EP",
    "secondaryTypes": ["Compilation"],
    "releaseDate": "2004-01-01T00:00:00Z",
}


def test_a_lidarr_import_carries_its_album_title_type_and_year():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(title="Diplo", year=None)])
    app = _LidarrHistoryARR([_lidarr_import()], [_lidarr_delete()], [_FAVELA])

    completed = _collect(module, app, grabs)

    assert app.album_lookups == [[31]]
    assert completed[0]["replaced"] is True
    assert completed[0]["album"] == {
        "title": "Favela on Blast: Rio Baile Funk 04",
        "type": "EP",
        "year": 2004,
    }
    label = "Diplo - Favela on Blast: Rio Baile Funk 04 (2004) [EP]"
    assert f"{label} — upgraded" in _embed_body(completed)
    assert f"  {label}" in _run_log(module, completed).split("\n")


@pytest.mark.parametrize("albums", [None, RuntimeError("lidarr down")])
def test_a_failed_album_lookup_still_reports_the_import(albums):
    """The album is display only: losing it must never lose the import report."""
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab(title="Diplo", year=None)])
    app = _LidarrHistoryARR([_lidarr_import()], [_lidarr_delete()], albums)

    seen = module._collect_completed_imports(app, grabs)
    completed, resolved, _pending = seen.completed, seen.resolved, seen.pending

    assert resolved == {"dl-1"}
    assert "album" not in completed[0]
    assert "Diplo — upgraded" in _embed_body(completed)



def _failure(download_id="dl-1", message="Duplicate NZB"):
    return {
        "downloadId": download_id,
        "movieId": 7,
        "eventType": "downloadFailed",
        "date": "2026-08-29T11:00:00Z",
        "data": {"message": message},
    }


def test_a_failed_download_is_reported_with_the_arrs_reason_and_settled():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([], [], failures=[_failure()])

    seen = module._collect_completed_imports(app, grabs)

    assert seen.completed == []
    assert seen.resolved == {"dl-1"}
    assert [(row["download"], row["reason"]) for row in seen.not_imported] == [
        ("Movie.2024.REMUX-GRP", "Duplicate NZB")
    ]
    assert grabs.pruned == [("radarr", upgradinatorr_module.GRAB_PRUNE_DAYS)]


def test_a_grab_past_the_retention_window_is_reported_as_not_imported():
    module = make_upgradinatorr(dry_run=False)
    stale = _pending_since(hours=24 * upgradinatorr_module.GRAB_RETENTION_DAYS + 1)
    fresh = _pending_since(hours=24 * upgradinatorr_module.GRAB_RETENTION_DAYS - 1)
    grabs = _FakeGrabs(
        [_grab("stale", grabbed_at=stale), _grab("fresh", grabbed_at=fresh)]
    )
    app = _HistoryARR([], [])

    seen = module._collect_completed_imports(app, grabs)

    assert seen.resolved == {"stale"}
    assert [row["reason"] for row in seen.not_imported] == [
        f"not imported after {upgradinatorr_module.GRAB_RETENTION_DAYS} days"
    ]
    assert seen.pending == 2


def test_an_import_wins_over_an_earlier_failure_of_the_same_download():
    module = make_upgradinatorr(dry_run=False)
    grabs = _FakeGrabs([_grab()])
    app = _HistoryARR([_import()], [], failures=[_failure()])

    seen = module._collect_completed_imports(app, grabs)

    assert [row["download"] for row in seen.completed] == ["Movie.2024.REMUX-GRP"]
    assert seen.not_imported == ()


def test_unreadable_failures_still_report_imports_and_keep_the_rest_pending():
    """Only the failure read degrades: imports still report, and nothing else is
    settled, so a failed or stale grab is judged again next run."""
    module = make_upgradinatorr(dry_run=False)
    old = _pending_since(hours=24 * upgradinatorr_module.GRAB_RETENTION_DAYS + 1)
    grabs = _FakeGrabs([_grab("dl-1"), _grab("old", grabbed_at=old)])
    app = _HistoryARR([_import()], [], failures=())
    app._by_event[app.history_failed_event] = None

    seen = module._collect_completed_imports(app, grabs)

    assert [row["download"] for row in seen.completed] == ["Movie.2024.REMUX-GRP"]
    assert seen.resolved == {"dl-1"}
    assert seen.not_imported == ()


def test_a_failed_grab_alone_survives_the_nothing_left_to_search_bail_out(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    UpgradinatorrGrabs(StubLogger(), db_path=isolated_db).record(
        "radarr", [_grab()], grabbed_at=_pending_since()
    )
    app = _HistoryARR([], [], media=[], failures=[_failure()])

    result = module.process_instance("radarr", _upgrade_settings(unattended=False), app)

    assert result is not None, "the bail-out dropped a failed grab"
    assert [row["reason"] for row in result["not_imported"]] == ["Duplicate NZB"]
    assert result["resolved_grabs"] == ["dl-1"]
    log = _run_log_output(module, result)
    assert "[NOT IMPORTED] 1 grab(s) from earlier runs:" in log
    assert "Movie.2024.REMUX-GRP — Duplicate NZB" in log


def _run_log_output(module, run):
    """print_output's info lines for one instance's result, with a capturing logger."""

    class _Capture(StubLogger):
        def __init__(self):
            super().__init__()
            self.lines = []

        def info(self, *args, **kwargs):
            self.lines.append(" ".join(str(a) for a in args))

    module.logger = _Capture()
    module.print_output({"radarr": run})
    return "\n".join(module.logger.lines)

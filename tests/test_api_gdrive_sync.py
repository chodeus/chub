"""POST /posters/gdrive/sync reports the job that will really sync the folders."""

import json
from types import SimpleNamespace

import pytest

from backend.api.posters import gdrive
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    folders = [SimpleNamespace(name=n) for n in ("Movies", "TV", "Anime")]
    monkeypatch.setattr(
        gdrive,
        "SyncGDrive",
        lambda logger: SimpleNamespace(config=SimpleNamespace(gdrive_list=folders)),
    )
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _sync(db, *names):
    resp = gdrive.sync_gdrive_folders(gdrive_names=list(names), logger=_logger(), db=db)
    return resp.status_code, json.loads(resp.body)


def _jobs(db):
    return db.worker.execute_query("SELECT id FROM jobs", fetch_all=True)


def test_a_new_sync_is_reported_as_queued(db):
    status, body = _sync(db, "Movies")

    assert status == 200
    assert body["message"] == "GDrive sync queued for 'Movies'"
    job = db.worker.get_job_by_id("jobs", body["data"]["job_id"])
    assert json.loads(job["payload"])["module_args"]["only_folders"] == ["Movies"]


@pytest.mark.parametrize(
    "first, then, claim, expected",
    [
        (
            ("Movies", "TV", "Anime"),
            ("Movies",),
            False,
            "A GDrive sync covering 'Movies' is already queued (job {id})",
        ),
        (
            ("Movies", "TV"),
            ("TV", "Movies"),
            True,
            "A GDrive sync covering 2 folders: Movies, TV is already running (job {id})",
        ),
    ],
    ids=["all-folders-job-queued", "same-subset-running"],
)
def test_a_sync_already_covering_the_folders_is_named(db, first, then, claim, expected):
    _, queued = _sync(db, *first)
    first_id = queued["data"]["job_id"]
    if claim:
        db.worker.claim_next_job("jobs")

    status, body = _sync(db, *then)

    assert status == 200
    assert body["message"] == expected.format(id=first_id)
    assert (body["data"]["job_id"], body["data"]["deduped"]) == (first_id, True)
    assert len(_jobs(db)) == 1


@pytest.mark.parametrize(
    "first, then, claim, expected",
    [
        (
            ("TV",),
            ("Movies",),
            True,
            "Another GDrive sync is already running (job {id}); "
            "sync 'Movies' again once it finishes",
        ),
        (
            ("Movies", "TV"),
            ("Movies", "TV", "Anime"),
            False,
            "Another GDrive sync is already queued (job {id}); "
            "sync all 3 folders again once it finishes",
        ),
    ],
    ids=["other-folder-running", "subset-queued-full-requested"],
)
def test_a_sync_skipping_the_folders_is_refused_not_reported(
    db, first, then, claim, expected
):
    _, queued = _sync(db, *first)
    if claim:
        db.worker.claim_next_job("jobs")

    status, body = _sync(db, *then)

    assert status == 409
    assert body["error_code"] == "GDRIVE_SYNC_BUSY"
    assert body["message"] == expected.format(id=queued["data"]["job_id"])
    assert len(_jobs(db)) == 1

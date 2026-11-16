"""The Run Summary's lines for each step result, and its Result line."""

import pytest

from backend.util.connector import SyncResult
from backend.util.run_summary import RunSummary, result_text
from tests.conftest import StubLogger


def _lines(record, *results):
    """The info lines RunSummary logs after its header for one step's results, then a clean run."""
    summary, logger = RunSummary(), StubLogger()
    for result in results:
        getattr(summary, record)(result)
    summary.log(logger, None, None, cancelled=False, dry_run=False)
    return logger.messages["info"][1:]


def _sync(total, synced, failed=0, changes="1 copied"):
    return {"total": total, "synced": synced, "failed": failed, "changes": changes}


@pytest.mark.parametrize(
    ("summary", "line"),
    [
        (_sync(5, 5), "GDrive sync      : 5/5 folders, 1 copied"),
        (_sync(5, 2), "GDrive sync      : ❌ stopped after 2/5 folders, 1 copied"),
        (_sync(5, 0), "GDrive sync      : ❌ stopped after 0/5 folders"),
        (None, "GDrive sync      : ❌ stopped before it counted its folders"),
        ({**_sync(5, 3, failed=2), "dry_run": True}, "GDrive sync      : ❌ [DRY RUN] 2/5 folders failed"),
        ({**_sync(5, 2), "dry_run": True}, "GDrive sync      : ❌ [DRY RUN] stopped after 2/5 folders, 1 copied"),
    ],
)
def test_a_drive_sync_line(summary, line):
    lines = _lines("gdrive", summary)
    assert lines[0] == line


def _arr(name, error=None):
    return SyncResult(instance_name=name, instance_type="radarr", success=error is None, error_message=error)


@pytest.mark.parametrize(
    ("results", "line"),
    [
        ([], "Arr sync         : no arr instances"),
        ([_arr("radarr1"), _arr("sonarr1")], "Arr sync         : 2/2 instances synced"),
        (
            [_arr("radarr1", "timed out"), _arr("sonarr1"), _arr("sonarr2", "401")],
            "Arr sync         : ❌ 1/3 instances synced, radarr1: timed out (+1 more)",
        ),
    ],
)
def test_an_arr_sync_line(results, line):
    lines = _lines("arr", results)
    assert lines[0] == line


def _upload(updated, failed, *errors):
    """PosterUploader._compile_final_result's shape: success needs no failures and one instance without an error."""
    instances = [{"instance": f"plex{i}", "error": e} for i, e in enumerate(errors)]
    return {
        "success": failed == 0 and any(e is None for e in errors),
        "message": "Upload complete",
        "payload": {"updated": updated, "failed": failed, "instance_results": instances},
    }


@pytest.mark.parametrize(
    ("result", "line"),
    [
        (_upload(5, 0, None), "Plex upload      : 5 uploaded, 0 failed"),
        (_upload(5, 2, None), "Plex upload      : ❌ 5 uploaded, 2 failed"),
        (
            _upload(5, 0, None, "Connection refused"),
            "Plex upload      : ❌ 5 uploaded, 0 failed, 1 instance with errors (Connection refused)",
        ),
    ],
)
def test_a_plex_upload_line(result, line):
    lines = _lines("upload", result)
    assert lines[0] == line


def test_failed_asset_applies_are_counted_and_fail_the_run_line():
    entry = {"title": "Dune", "year": 2021, "source": "local", "dry_run": False}
    output = {
        "logo": [{**entry, "applied": True, "reason": "/k/a.png"}] * 3,
        "banner": [{**entry, "applied": False, "reason": "permission denied"}],
    }
    lines = _lines("assets", output)
    assert lines == [
        "Asset renamerr   : ❌ 3 logos, 0 banners applied, 1 failed",
        "Result           : ⚠ finished, with failures above",
    ]


def test_a_step_result_it_cannot_read_costs_only_that_line():
    summary, logger = RunSummary(), StubLogger()
    summary.upload(None)
    summary.assets({"logo": [{"applied": True}]})
    summary.log(logger, None, None, cancelled=False, dry_run=False)
    error = "AttributeError: 'NoneType' object has no attribute 'get'"
    assert logger.messages["info"][1:] == [
        f"Plex upload      : ❌ could not summarise this step ({error})",
        "Asset renamerr   : 1 logo applied",
        "Result           : ⚠ finished, with failures above",
    ]


def test_a_step_is_named_only_when_its_own_error_ended_the_run():
    swallowed, later = RuntimeError("sync broke"), ValueError("later")
    assert result_text(later, ("sync_gdrive", swallowed), cancelled=False) == "❌ failed: later"
    assert result_text(swallowed, ("sync_gdrive", swallowed), cancelled=False) == (
        "❌ failed at sync_gdrive: sync broke"
    )


def test_an_error_with_no_message_shows_its_type():
    assert result_text(KeyError(), None, cancelled=False) == "❌ failed: KeyError"

"""Tests for the CL2K background season workers' failure contract.

Both workers promise "never raises — a crash is recorded as the job's error so
the frontend poll terminates instead of spinning on a stuck 'running'". They run
on a bare thread, so nothing above them catches anything: whatever escapes the
worker leaves the job registry saying "running" forever and the maker's poll
never terminates. That makes the guard's coverage the whole contract — every
call the worker makes, including loading config, has to sit inside it.
"""

import types

import pytest

pytest.importorskip("wand.image")  # cl2k extra (the module imports the renderer)

import backend.api.cl2k_maker as api  # noqa: E402
from backend.util.config import ConfigParseError  # noqa: E402


@pytest.fixture
def logger():
    return types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


def _job_state(jid):
    with api._season_jobs_lock:
        return dict(api._season_jobs[jid])


@pytest.mark.parametrize("worker", ["retext", "seasons"])
def test_config_failure_fails_the_job_rather_than_the_thread(worker, logger, monkeypatch):
    """A broken config file must land as job status "error", not escape the worker.

    A ConfigParseError is the realistic trigger: config.yaml is edited to
    something malformed while a season batch is queued.
    """
    monkeypatch.setattr(
        api,
        "load_config",
        lambda *a, **k: (_ for _ in ()).throw(ConfigParseError("bad YAML at line 3")),
    )
    jid = api._new_season_job(1, "Some Show")

    if worker == "retext":
        req = api.RetextSeasonsRequest(seasons=[1], tmdb_id=1, title="Some Show")
        api._run_retext_seasons_job(jid, object(), logger, b"", req)
    else:
        req = api.SeasonsRequest(seasons=[1], tmdb_id=1, title="Some Show")
        api._run_seasons_job(jid, object(), logger, req)

    job = _job_state(jid)
    assert job["status"] == "error"
    assert "bad YAML" in job["error"]

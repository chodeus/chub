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


@pytest.mark.parametrize("worker", ["retext", "seasons"])
def test_each_season_reads_live_config(worker, logger, monkeypatch):
    """Config is REPLACED on reload, so a batch must re-read it per season.

    Snapshotting it before the loop renders every later season with the settings
    the user just changed away from — silently, and only for long batches. Both
    workers, because the full-CL2K one runs the *longer* batch of the two.
    """
    seen = []
    monkeypatch.setattr(api, "load_config", lambda *a, **k: seen.append(1) or "cfg")

    jid = api._new_season_job(3, "Some Show")
    if worker == "retext":
        monkeypatch.setattr(api, "retext_poster", lambda **kw: {"status": "generated"})
        req = api.RetextSeasonsRequest(seasons=[1, 2, 3], tmdb_id=1, title="Some Show")
        api._run_retext_seasons_job(jid, object(), logger, b"", req)
    else:
        monkeypatch.setattr(api, "generate_seasons", lambda **kw: {"results": []})
        req = api.SeasonsRequest(seasons=[1, 2, 3], tmdb_id=1, title="Some Show")
        api._run_seasons_job(jid, object(), logger, req)

    assert len(seen) == 3, "config was snapshotted for the batch, not read per season"
    assert _job_state(jid)["status"] == "done"

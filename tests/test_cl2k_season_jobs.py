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


def _fake_generate_seasons(**kw):
    """Stand-in for the real one, which reports each season through progress_cb.

    A stub that just returns leaves job["done"] at 0 and quietly makes any
    progress assertion vacuous.
    """
    for n in kw["seasons"]:
        kw["progress_cb"]({"season": int(n), "status": "generated"})
    return {"results": []}


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
def test_a_mid_batch_config_failure_keeps_the_seasons_already_done(worker, logger, monkeypatch):
    """Per-season loading means a fault can land mid-batch, not just up front.

    The seasons already rendered must stay in the registry and the rest must not
    run — a one-season case can't tell "stopped after 1" from "never started".
    """
    calls = []

    def _load(*a, **k):
        calls.append(1)
        if len(calls) > 1:
            raise ConfigParseError("bad YAML at line 3")
        return "cfg"

    monkeypatch.setattr(api, "load_config", _load)
    jid = api._new_season_job(3, "Some Show")

    if worker == "retext":
        monkeypatch.setattr(api, "retext_poster", lambda **kw: {"status": "generated"})
        req = api.RetextSeasonsRequest(seasons=[1, 2, 3], tmdb_id=1, title="Some Show")
        api._run_retext_seasons_job(jid, object(), logger, b"", req)
    else:
        monkeypatch.setattr(api, "generate_seasons", _fake_generate_seasons)
        req = api.SeasonsRequest(seasons=[1, 2, 3], tmdb_id=1, title="Some Show")
        api._run_seasons_job(jid, object(), logger, req)

    job = _job_state(jid)
    assert job["status"] == "error"
    assert "bad YAML" in job["error"]
    assert job["done"] == 1, "season 1 completed before the fault and must still count"
    assert len(calls) == 2, "the batch must stop at the fault, not carry on to season 3"


@pytest.mark.parametrize("field", ["backdrop_b64", "logo_b64"])
def test_malformed_base64_fails_the_job_rather_than_the_thread(field, logger, monkeypatch):
    """The blobs are decoded once for the batch, but still inside the guard.

    Decoding above the try is the tempting way to hoist it out of the loop, and
    it silently breaks the never-raise contract: b64decode raises on bad padding,
    the bare thread dies, and the job polls "running" forever.
    """
    monkeypatch.setattr(api, "load_config", lambda *a, **k: "cfg")
    monkeypatch.setattr(api, "generate_seasons", _fake_generate_seasons)
    jid = api._new_season_job(1, "Some Show")
    req = api.SeasonsRequest(seasons=[1], tmdb_id=1, title="Some Show", **{field: "!!!not-b64"})

    api._run_seasons_job(jid, object(), logger, req)

    assert _job_state(jid)["status"] == "error"


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
        monkeypatch.setattr(api, "generate_seasons", _fake_generate_seasons)
        req = api.SeasonsRequest(seasons=[1, 2, 3], tmdb_id=1, title="Some Show")
        api._run_seasons_job(jid, object(), logger, req)

    assert len(seen) == 3, "config was snapshotted for the batch, not read per season"
    assert _job_state(jid)["status"] == "done"


def test_the_batch_carries_the_logo_edits_the_preview_was_built_with(logger, monkeypatch):
    """A season batch reuses ONE logo, so it must reuse that logo's edits too.

    The masks are keyed to the logo in the UI, so dropping them here doesn't fail —
    it quietly bulk-generates every season from an unedited logo while the preview
    beside it shows the edited one.
    """
    seen = {}

    def _capture(**kw):
        seen.update(kw)
        for n in kw["seasons"]:
            kw["progress_cb"]({"season": int(n), "status": "generated"})
        return {"results": []}

    monkeypatch.setattr(api, "load_config", lambda *a, **k: "cfg")
    monkeypatch.setattr(api, "generate_seasons", _capture)
    jid = api._new_season_job(1, "Some Show")
    req = api.SeasonsRequest(
        seasons=[1],
        tmdb_id=1,
        title="Some Show",
        logo_flip_b64="aGVsbG8=",  # "hello"
        logo_erase_b64="d29ybGQ=",  # "world"
    )

    api._run_seasons_job(jid, object(), logger, req)

    assert _job_state(jid)["status"] == "done"
    assert seen.get("logo_flip_bytes") == b"hello"
    assert seen.get("logo_erase_bytes") == b"world"


@pytest.mark.parametrize("field", ["logo_flip_b64", "logo_erase_b64"])
def test_malformed_logo_edit_masks_fail_the_job_rather_than_the_thread(field, logger, monkeypatch):
    """Same never-raise contract as the other blobs — decoded inside the guard."""
    monkeypatch.setattr(api, "load_config", lambda *a, **k: "cfg")
    monkeypatch.setattr(api, "generate_seasons", _fake_generate_seasons)
    jid = api._new_season_job(1, "Some Show")
    req = api.SeasonsRequest(seasons=[1], tmdb_id=1, title="Some Show", **{field: "!!!not-b64"})

    api._run_seasons_job(jid, object(), logger, req)

    assert _job_state(jid)["status"] == "error"


# --- season list cleaning + job-start guard ---


def test_clean_seasons_dedupes_orders_and_drops_negatives():
    assert api._clean_seasons([3, 1, 2, 2, 1]) == [1, 2, 3]
    assert api._clean_seasons([0, 5, -1, "x", None, 3]) == [0, 3, 5]
    assert api._clean_seasons(None) == []


def test_spawn_season_job_marks_error_when_the_thread_cannot_start(logger, monkeypatch):
    """A thread that can't spawn must land as job status "error" + a 503, not leave
    the job polling "running" forever."""

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start a thread")

    monkeypatch.setattr(api.threading, "Thread", _Boom)
    jid = api._new_season_job(1, "Some Show")
    resp = api._spawn_season_job(jid, lambda: None, (), name="cl2k-x", logger=logger)
    assert resp is not None and resp.status_code == 503
    assert _job_state(jid)["status"] == "error"


def test_generate_seasons_endpoint_rejects_too_many(logger):
    """A list longer than _MAX_SEASONS is a visible error, never silent truncation."""
    req = api.SeasonsRequest(
        tmdb_id=1, title="X", seasons=list(range(api._MAX_SEASONS + 5))
    )
    resp = api.generate_seasons_endpoint(req, db=object(), logger=logger)
    assert resp.status_code == 400
    assert b"CL2K_TOO_MANY_SEASONS" in resp.body


def test_generate_seasons_endpoint_cleans_the_list_before_spawning(logger, monkeypatch):
    """The worker iterates req.seasons, so the endpoint must reassign the cleaned
    (deduped, ordered) list onto the request before spawning."""
    captured = {}

    def _fake_spawn(jid, target, args, *, name, logger):
        captured["seasons"] = args[3].seasons
        return None

    monkeypatch.setattr(api, "_spawn_season_job", _fake_spawn)
    req = api.SeasonsRequest(tmdb_id=1, title="X", seasons=[2, 1, 2, 1, 3])
    api.generate_seasons_endpoint(req, db=object(), logger=logger)
    assert captured["seasons"] == [1, 2, 3]

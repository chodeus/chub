"""Tests for hard-disabling modules (general.disabled_modules) — the helper
plus the orchestrator's skip gate used by scheduled / manual / webhook runs."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backend.util.job_processor as jp  # noqa: E402
from backend.util.config import ChubConfig, module_is_disabled  # noqa: E402
from backend.util.module_orchestrator import ModuleOrchestrator  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


def test_module_is_disabled_reads_config():
    cfg = SimpleNamespace(general=SimpleNamespace(disabled_modules=["nohl", "jduparr"]))
    assert module_is_disabled("nohl", cfg) is True
    assert module_is_disabled("jduparr", cfg) is True
    assert module_is_disabled("poster_renamerr", cfg) is False


def test_module_is_disabled_empty_default():
    cfg = SimpleNamespace(general=SimpleNamespace(disabled_modules=[]))
    assert module_is_disabled("poster_renamerr", cfg) is False


def test_module_is_disabled_fails_closed_on_config_error(monkeypatch):
    """An unreadable config must skip the run — these modules mutate the disk."""

    def boom(*_a, **_kw):
        """Stand-in load_config that fails."""
        raise RuntimeError("config.yml is unparseable")

    monkeypatch.setattr("backend.util.config.load_config", boom)
    assert module_is_disabled("poster_renamerr") is True


def test_orchestrator_async_skips_disabled():
    orch = ModuleOrchestrator(logger=StubLogger())
    with patch("backend.util.config.module_is_disabled", return_value=True):
        res = orch.run_module_async("nohl", "scheduled")
    assert res["success"] is False
    assert res["disabled"] is True


def test_orchestrator_immediate_skips_disabled():
    orch = ModuleOrchestrator(logger=StubLogger())
    with patch("backend.util.config.module_is_disabled", return_value=True):
        res = orch.run_module_immediate("nohl", "web")
    assert res["success"] is False
    assert res["disabled"] is True


def _config_with_disabled(monkeypatch, *names):
    cfg = ChubConfig(general={"disabled_modules": list(names)})
    monkeypatch.setattr("backend.util.config.load_config", lambda *a, **k: cfg)


def _webhook_job():
    return {"id": 11, "type": "webhook", "payload": '{"webhook_data": {}}'}


def _track_webhook_processor(monkeypatch):
    built = []

    class _Processor:
        def __init__(self, *_a, **_kw):
            built.append(True)
            raise RuntimeError("stop after the gate")

    monkeypatch.setattr("backend.util.webhook_processor.WebhookProcessor", _Processor)
    return built


def test_webhook_job_skips_when_poster_renamerr_disabled(monkeypatch):
    _config_with_disabled(monkeypatch, "poster_renamerr")
    built = _track_webhook_processor(monkeypatch)
    res = jp.process_job(_webhook_job(), StubLogger())
    assert res["success"] is True
    assert res["disabled"] is True
    assert built == []


def test_webhook_job_runs_when_poster_renamerr_enabled(monkeypatch):
    _config_with_disabled(monkeypatch, "nohl")
    built = _track_webhook_processor(monkeypatch)
    res = jp.process_job(_webhook_job(), StubLogger())
    assert built == [True]
    assert "disabled" not in res


def test_module_run_job_skips_disabled_module(monkeypatch):
    _config_with_disabled(monkeypatch, "unmatched_assets")
    job = {
        "id": 12,
        "type": "module_run",
        "payload": '{"module_name": "unmatched_assets"}',
    }
    res = jp.process_job(job, StubLogger())
    assert res["success"] is True
    assert res["disabled"] is True


def test_module_run_job_passes_gate_when_enabled(monkeypatch):
    _config_with_disabled(monkeypatch)
    job = {
        "id": 13,
        "type": "module_run",
        "payload": '{"module_name": "no_such_module"}',
    }
    res = jp.process_job(job, StubLogger())
    assert "disabled" not in res
    assert res["success"] is False


def test_webhook_job_skips_when_config_unreadable(monkeypatch):
    def boom(*_a, **_kw):
        """Stand-in load_config that fails."""
        raise RuntimeError("config.yml is unparseable")

    monkeypatch.setattr("backend.util.config.load_config", boom)
    built = _track_webhook_processor(monkeypatch)
    res = jp.process_job(_webhook_job(), StubLogger())
    assert res["disabled"] is True
    assert built == []


@pytest.mark.parametrize(
    "job_type, handler, module",
    [
        ("poster_rename", "_process_poster_rename_job", "poster_renamerr"),
        ("upload_posters", "_process_upload_posters_job", "poster_renamerr"),
        ("labelarr_bulk_sync", "_process_labelarr_bulk_sync_job", "labelarr"),
    ],
)
@pytest.mark.parametrize("disabled", [True, False])
def test_module_work_jobs_follow_their_module(
    monkeypatch, job_type, handler, module, disabled
):
    _config_with_disabled(monkeypatch, *([module] if disabled else []))
    ran = []
    monkeypatch.setattr(
        jp, handler, lambda *a, **k: ran.append(True) or {"success": True}
    )
    res = jp.process_job({"id": 14, "type": job_type, "payload": "{}"}, StubLogger())
    if disabled:
        assert res["disabled"] is True
        assert ran == []
    else:
        assert ran == [True]

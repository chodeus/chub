"""Tests for hard-disabling modules (general.disabled_modules) — the helper
plus the orchestrator's skip gate used by scheduled / manual / webhook runs."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.config import module_is_disabled  # noqa: E402
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

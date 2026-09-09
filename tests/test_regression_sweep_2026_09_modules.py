"""Regression tests for the 2026-09 sweep, modules batch — one per confirmed bug."""

import os

import pytest


# ---------------------------------------------------------------------------
# An unreadable source dir aborted the whole nohl run
# ---------------------------------------------------------------------------


class _Logger:
    def __init__(self):
        self.records = []

    def __getattr__(self, _name):
        return lambda *a, **k: self.records.append(" ".join(str(x) for x in a))


@pytest.mark.parametrize(
    "exc",
    [
        PermissionError(13, "Permission denied"),      # PUID/PGID lacks read
        OSError(116, "Stale file handle"),             # dropped NFS mount
        OSError(5, "Input/output error"),              # degraded pool
    ],
)
def test_unreadable_source_dir_is_skipped_not_fatal(monkeypatch, exc):
    """Only FileNotFoundError was caught, so a sibling OSError aborted the run."""
    from backend.modules.nohl import Nohl

    def boom(_path):
        raise exc

    monkeypatch.setattr(os, "listdir", boom)
    logger = _Logger()

    result = Nohl.find_nohl_files("/mnt/unreadable", logger)

    assert result is None
    assert any("unreadable" in r or "denied" in r.lower() or "error" in r.lower()
               for r in logger.records)


def test_missing_source_dir_still_skipped(monkeypatch):
    """The original FileNotFoundError behaviour must survive the widening."""
    from backend.modules.nohl import Nohl

    def boom(_path):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(os, "listdir", boom)
    assert Nohl.find_nohl_files("/mnt/gone", _Logger()) is None


# ---------------------------------------------------------------------------
# Schedule blocks and upgradinatorr profiles re-fired every tick within a minute
# ---------------------------------------------------------------------------


class _FixedNow:
    """datetime stand-in pinned to one matched minute."""

    @staticmethod
    def _cls():
        from datetime import datetime as _dt

        class F(_dt):
            @classmethod
            def now(cls, tz=None):
                return cls(2024, 5, 6, 9, 0, tzinfo=tz)

        return F


class _Orch:
    def __init__(self):
        self.calls = []

    def get_module_status(self, name):
        return {"running": False}

    def run_module_async(self, *args, **kwargs):
        self.calls.append(args[0])
        return {"success": True, "data": {}}


def _fresh_scheduler(monkeypatch, cfg):
    import backend.util.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "datetime", _FixedNow._cls())
    sched_mod._last_fired.clear()
    orch = _Orch()
    return sched_mod.ChubScheduler(cfg, logger=None, module_orchestrator=orch), orch


def test_schedule_blocks_fire_once_per_matched_minute(monkeypatch):
    """The 5s tick re-entered the same matched minute and re-enqueued the block."""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        schedule={},
        upgradinatorr=SimpleNamespace(instances_list=[]),
        schedule_blocks={
            "border_replacerr": [
                {"enabled": True, "schedule": "daily(09:00)", "label": "morning"}
            ]
        },
    )
    s, orch = _fresh_scheduler(monkeypatch, cfg)

    for _ in range(5):  # five 5s ticks inside the same minute
        s._tick_schedule_blocks(set(), set())

    assert orch.calls == ["border_replacerr"]


def test_upgradinatorr_profiles_fire_once_per_matched_minute(monkeypatch):
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        schedule={},
        schedule_blocks={},
        upgradinatorr=SimpleNamespace(
            instances_list=[
                {"enabled": True, "schedule": "daily(09:00)", "name": "radarr-main"}
            ]
        ),
    )
    s, orch = _fresh_scheduler(monkeypatch, cfg)

    for _ in range(5):
        s._tick_upgradinatorr_profiles(set())

    assert orch.calls == ["upgradinatorr"]

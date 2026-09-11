"""Regression tests for the 2026-09 sweep, modules batch — one per confirmed bug."""

import os

import pytest


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
    """Any OSError on the top-level listdir skips that source dir."""
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
    """A missing source dir is skipped."""
    from backend.modules.nohl import Nohl

    def boom(_path):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(os, "listdir", boom)
    result = Nohl.find_nohl_files("/mnt/gone", _Logger())
    assert result is None


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


class _FailOnceOrch(_Orch):
    def run_module_async(self, *args, **kwargs):
        self.calls.append(args[0])
        if len(self.calls) == 1:
            return {"success": False, "message": "database is locked"}
        return {"success": True, "data": {}}


def _fresh_scheduler(monkeypatch, cfg, orch=None):
    import backend.util.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "datetime", _FixedNow._cls())
    sched_mod._last_fired.clear()
    orch = orch or _Orch()
    return sched_mod.ChubScheduler(cfg, logger=None, module_orchestrator=orch), orch


def test_failed_module_queue_retries_within_the_matched_minute(monkeypatch):
    """A failed enqueue leaves the minute unfired, so the next tick retries once."""
    from types import SimpleNamespace

    import backend.util.config as config_mod

    cfg = SimpleNamespace(
        general=SimpleNamespace(disabled_modules=[]),
        instances=SimpleNamespace(sync_schedule=""),
        schedule={},
        schedule_blocks={},
        upgradinatorr=SimpleNamespace(instances_list=[]),
    )
    monkeypatch.setattr(config_mod, "load_config", lambda: cfg)
    s, orch = _fresh_scheduler(monkeypatch, cfg, _FailOnceOrch())

    for _ in range(4):
        s._tick({"nohl": "daily(09:00)"})

    assert orch.calls == ["nohl", "nohl"]


def test_schedule_blocks_fire_once_per_matched_minute(monkeypatch):
    """Repeated ticks within one matched minute enqueue a block once."""
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

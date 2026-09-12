"""Regression tests for the 2026-09 sweep, modules batch — one per confirmed bug."""

import os
from datetime import datetime

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
        FileNotFoundError(2, "No such file or directory"),  # source dir removed
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
    logged = any("/mnt/unreadable" in r for r in logger.records)

    assert result is None
    assert logged


def _clock(*times):
    """datetime stand-in: now() returns `times` in order, then repeats the last."""
    pending = list(times)

    class _Clock(datetime):
        reads = 0

        @classmethod
        def now(cls, tz=None):
            cls.reads += 1
            return pending.pop(0) if len(pending) > 1 else pending[0]

    return _Clock


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


def _fresh_scheduler(monkeypatch, cfg, orch=None, clock=None):
    import backend.util.scheduler as sched_mod

    clock = clock or _clock(datetime(2024, 5, 6, 9, 0))
    monkeypatch.setattr(sched_mod, "datetime", clock)
    sched_mod._last_fired.clear()
    orch = orch or _Orch()
    return sched_mod.ChubScheduler(cfg, logger=None, module_orchestrator=orch), orch


def _tick_scheduler(monkeypatch, orch=None, clock=None):
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
    return _fresh_scheduler(monkeypatch, cfg, orch, clock)


def test_failed_module_queue_retries_within_the_matched_minute(monkeypatch):
    """A failed enqueue leaves the minute unfired, so the next tick retries once."""
    s, orch = _tick_scheduler(monkeypatch, _FailOnceOrch())

    for _ in range(4):
        s._tick({"nohl": "daily(09:00)"})

    assert orch.calls == ["nohl", "nohl"]


def test_minute_boundary_match_and_guard_share_one_clock_read(monkeypatch):
    """A tick straddling 09:00/09:01 must not record 09:01 and swallow its run."""
    clock = _clock(
        datetime(2024, 5, 6, 9, 0, 59, 999999),
        datetime(2024, 5, 6, 9, 1, 0, 1),
        datetime(2024, 5, 6, 9, 1, 5),
    )
    s, orch = _tick_scheduler(monkeypatch, clock=clock)

    for _ in range(2):
        s._tick({"nohl": "daily(09:00|09:01)"})

    assert orch.calls == ["nohl", "nohl"]


def test_tick_reads_the_clock_once_for_every_phase(monkeypatch):
    """Modules, profiles and blocks in one tick all evaluate the same instant."""
    clock = _clock(datetime(2024, 5, 6, 9, 0))
    s, orch = _tick_scheduler(monkeypatch, clock=clock)
    s.config.upgradinatorr.instances_list = [
        {"enabled": True, "schedule": "daily(09:00)", "name": "radarr-main"}
    ]
    s.config.schedule_blocks = {
        "border_replacerr": [
            {"enabled": True, "schedule": "daily(09:00)", "label": "morning"}
        ]
    }

    s._tick({"nohl": "daily(09:00)"})

    assert orch.calls == ["nohl", "upgradinatorr", "border_replacerr"]
    assert clock.reads == 1


def test_cron_failed_dispatch_retries_next_tick(monkeypatch):
    """A failed enqueue at a cron time retries on the next tick, not the next day."""
    clock = _clock(
        datetime(2024, 5, 6, 8, 59),
        datetime(2024, 5, 6, 9, 0),
        datetime(2024, 5, 6, 9, 0, 5),
        datetime(2024, 5, 6, 9, 0, 10),
    )
    s, orch = _tick_scheduler(monkeypatch, _FailOnceOrch(), clock)

    for _ in range(4):
        s._tick({"nohl": "cron(0 9 * * *)"})

    assert orch.calls == ["nohl", "nohl"]


def test_media_sync_enqueues_once_per_minute_and_retries_a_failure(monkeypatch):
    """media_sync enqueues once per matched minute and retries a failed enqueue."""
    from types import SimpleNamespace

    results = iter(
        [{"success": False, "message": "database is locked"}]
        + [{"success": True}] * 5
    )
    enqueued = []

    def enqueue_job(*args, **kwargs):
        enqueued.append(kwargs.get("job_type"))
        return next(results)

    orch = _Orch()
    orch.db = SimpleNamespace(worker=SimpleNamespace(enqueue_job=enqueue_job))
    s, _ = _fresh_scheduler(monkeypatch, SimpleNamespace(), orch)

    for _ in range(4):
        s._tick_media_sync("cron(0 9 * * *)")

    assert enqueued == ["media_sync", "media_sync"]


@pytest.mark.parametrize(
    "schedule,when,expected",
    [
        ("cron(0 9 * * *)", (9, 0, 45), True),
        ("cron(0 9 * * *)", (9, 1, 0), False),
        ("cron(0 9 * * * 30)", (9, 0, 10), True),
        ("cron(0 9 * * * 30)", (9, 1, 5), False),
        ("cron(0 9 * * * 58)", (9, 0, 55), True),  # last tick before :58
    ],
)
def test_cron_matches_any_fire_time_inside_the_minute(schedule, when, expected):
    """A seconds field must not make a 5s tick miss its minute."""
    import backend.util.scheduler as sched_mod

    result = sched_mod.check_schedule("x", schedule, None, datetime(2024, 5, 6, *when))
    assert result is expected


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


def test_reordered_or_renamed_config_does_not_refire_in_the_same_minute(monkeypatch):
    """A mid-minute reload that reorders or renames entries must not re-queue them."""
    from types import SimpleNamespace

    daily = "daily(09:00)"
    cfg = SimpleNamespace(
        schedule={},
        upgradinatorr=SimpleNamespace(
            instances_list=[
                {"schedule": daily, "label": "a", "instance": "radarr"},
                {"schedule": daily, "label": "b", "instance": "sonarr"},
            ]
        ),
        schedule_blocks={
            "border_replacerr": [
                {"schedule": daily, "label": "morning"},
                {"schedule": daily, "label": "extra"},
            ]
        },
    )
    s, orch = _fresh_scheduler(monkeypatch, cfg)
    s._tick_upgradinatorr_profiles(set())
    s._tick_schedule_blocks(set(), set())

    cfg.upgradinatorr.instances_list.reverse()
    cfg.schedule_blocks["border_replacerr"][0]["label"] = "renamed"
    s._tick_upgradinatorr_profiles(set())
    s._tick_schedule_blocks(set(), set())

    assert orch.calls == ["upgradinatorr", "border_replacerr"]


def test_plain_schedule_suppresses_blocks_and_profiles_all_minute(monkeypatch):
    """A module queued by its plain schedule is not re-queued by blocks or profiles."""
    s, orch = _tick_scheduler(monkeypatch)
    s.config.upgradinatorr.instances_list = [{"schedule": "daily(09:00)", "label": "a"}]
    s.config.schedule_blocks = {"nohl": [{"schedule": "daily(09:00)", "label": "m"}]}
    schedule = {"nohl": "daily(09:00)", "upgradinatorr": "daily(09:00)"}

    for _ in range(3):  # later ticks run after the first jobs have finished
        s._tick(schedule)

    assert orch.calls == ["nohl", "upgradinatorr"]

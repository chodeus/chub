"""Tests for backend/util/scheduler.py — schedule format parsing & dispatch."""

from datetime import datetime
from types import SimpleNamespace

import pytest

import backend.util.scheduler as scheduler

# Re-exports kept as module-level names so the test bodies stay readable;
# they all live on `scheduler` so monkeypatching `scheduler.datetime` is
# still effective.
ChubScheduler = scheduler.ChubScheduler
_iter_monthly_entries = scheduler._iter_monthly_entries
_iter_weekly_entries = scheduler._iter_weekly_entries
_normalize_weekday = scheduler._normalize_weekday
check_schedule = scheduler.check_schedule
print_schedule_table = scheduler.print_schedule_table


# --- Weekday normalization ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("mon", "monday"),
        ("MON", "monday"),
        ("monday", "monday"),
        ("1", "monday"),
        ("7", "sunday"),
        ("0", "sunday"),
        ("fri", "friday"),
        ("Thurs", "thursday"),
    ],
)
def test_normalize_weekday(raw, expected):
    assert _normalize_weekday(raw) == expected


def test_normalize_weekday_unknown_passes_through_lowercased():
    assert _normalize_weekday("notaday") == "notaday"


# --- Weekly / Monthly entry iteration ---


def test_iter_weekly_entries_comma_form():
    out = list(_iter_weekly_entries("Mon,Fri@09:00"))
    assert ("monday", "09:00") in out
    assert ("friday", "09:00") in out


def test_iter_weekly_entries_pipe_form():
    out = list(_iter_weekly_entries("monday@09:00|friday@10:00"))
    assert ("monday", "09:00") in out
    assert ("friday", "10:00") in out


def test_iter_weekly_entries_skips_malformed():
    # No @ -> skipped
    out = list(_iter_weekly_entries("nodayhere"))
    assert out == []


def test_iter_monthly_entries_comma_form():
    out = list(_iter_monthly_entries("1,15@09:00"))
    assert ("1", "09:00") in out
    assert ("15", "09:00") in out


# --- check_schedule frequencies ---


class FixedNow(datetime):
    target = (2024, 5, 6, 9, 0)

    @classmethod
    def now(cls, tz=None):
        return cls(*cls.target, tzinfo=tz)


def test_check_schedule_hourly_match(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    assert check_schedule("x", "hourly(0)", None) is True


def test_check_schedule_hourly_no_match(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    assert check_schedule("x", "hourly(30)", None) is False


def test_check_schedule_daily(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    assert check_schedule("x", "daily(09:00)", None) is True
    assert check_schedule("x", "daily(10:00)", None) is False


def test_check_schedule_daily_pipe_form(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    assert check_schedule("x", "daily(08:00|09:00|10:00)", None) is True


def test_check_schedule_weekly(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    # FixedNow = Monday 9am
    assert check_schedule("x", "weekly(monday@09:00)", None) is True
    assert check_schedule("x", "weekly(tuesday@09:00)", None) is False


def test_check_schedule_monthly(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    # FixedNow = day 6
    assert check_schedule("x", "monthly(6@09:00)", None) is True
    assert check_schedule("x", "monthly(7@09:00)", None) is False


def test_check_schedule_range_inside(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    # FixedNow = 2024-05-06
    assert check_schedule("x", "range(5/1-5/31)", None) is True


def test_check_schedule_range_outside(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    assert check_schedule("x", "range(1/1-1/31)", None) is False


def test_check_schedule_bad_format_returns_false(stub_logger):
    """No parens at all -> falls into ValueError handler."""
    assert check_schedule("x", "garbage", stub_logger) is False


def test_check_schedule_unknown_frequency_returns_false(stub_logger):
    assert check_schedule("x", "yearly(2024)", stub_logger) is False


# --- print_schedule_table ---


def test_print_schedule_table_no_logger():
    # Should be a no-op when logger is None
    print_schedule_table(None, {"x": "daily(09:00)"})


def test_print_schedule_table_with_logger(stub_logger):
    print_schedule_table(stub_logger, {"a": "daily(09:00)", "b": "weekly(mon@09:00)"})
    assert len(stub_logger.messages["info"]) >= 1


# --- ChubScheduler skip-when-running ---


class FakeOrchRunning:
    def __init__(self):
        self.calls = []

    def get_module_status(self, name):
        return {"running": True}

    def run_module_async(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"success": True, "data": {}}


def test_scheduler_skips_currently_running(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    cfg = SimpleNamespace(
        schedule={"upgradinatorr": "daily(09:00)"},
        upgradinatorr=SimpleNamespace(instances_list=[]),
    )
    orch = FakeOrchRunning()
    s = ChubScheduler(cfg, logger=None, module_orchestrator=orch)
    s._tick(cfg.schedule)
    assert orch.calls == []


class FakeOrchOK:
    def __init__(self):
        self.calls = []

    def get_module_status(self, name):
        return {"running": False}

    def run_module_async(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"success": True, "data": {}}


def test_scheduler_enqueues_due_module(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    cfg = SimpleNamespace(
        schedule={"nohl": "daily(09:00)"},
        upgradinatorr=SimpleNamespace(instances_list=[]),
    )
    orch = FakeOrchOK()
    s = ChubScheduler(cfg, logger=None, module_orchestrator=orch)
    s._tick(cfg.schedule)
    names = [c[0][0] for c in orch.calls]
    assert "nohl" in names


def test_scheduler_failed_queue_does_not_raise(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)

    class FakeOrchFail:
        def get_module_status(self, name):
            return {"running": False}

        def run_module_async(self, *a, **kw):
            return {"success": False, "message": "queue full"}

    cfg = SimpleNamespace(
        schedule={"nohl": "daily(09:00)"},
        upgradinatorr=SimpleNamespace(instances_list=[]),
    )
    s = ChubScheduler(cfg, logger=None, module_orchestrator=FakeOrchFail())
    # Should swallow the failure without raising
    s._tick(cfg.schedule)


def test_scheduler_upgradinatorr_profile_disabled_skipped(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    cfg = SimpleNamespace(
        schedule={},
        upgradinatorr=SimpleNamespace(
            instances_list=[
                SimpleNamespace(
                    label="disabled",
                    enabled=False,
                    schedule="daily(09:00)",
                    instance="radarr_main",
                )
            ]
        ),
    )
    orch = FakeOrchOK()
    s = ChubScheduler(cfg, logger=None, module_orchestrator=orch)
    s._tick(cfg.schedule)
    assert orch.calls == []


def test_scheduler_upgradinatorr_profile_no_schedule_skipped(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    cfg = SimpleNamespace(
        schedule={},
        upgradinatorr=SimpleNamespace(
            instances_list=[
                SimpleNamespace(
                    label="p", enabled=True, schedule="", instance="radarr_main"
                )
            ]
        ),
    )
    orch = FakeOrchOK()
    s = ChubScheduler(cfg, logger=None, module_orchestrator=orch)
    s._tick(cfg.schedule)
    assert orch.calls == []


def test_scheduler_does_not_double_run_upgradinatorr(monkeypatch):
    """If upgradinatorr was already queued via top-level schedule, skip profile dispatch."""
    monkeypatch.setattr(scheduler, "datetime", FixedNow)
    cfg = SimpleNamespace(
        schedule={"upgradinatorr": "daily(09:00)"},
        upgradinatorr=SimpleNamespace(
            instances_list=[
                SimpleNamespace(
                    label="p",
                    enabled=True,
                    schedule="daily(09:00)",
                    instance="radarr_main",
                )
            ]
        ),
    )
    orch = FakeOrchOK()
    s = ChubScheduler(cfg, logger=None, module_orchestrator=orch)
    s._tick(cfg.schedule)
    # Only one call, no profile-level dispatch
    assert len(orch.calls) == 1
    assert orch.calls[0][0][0] == "upgradinatorr"
    # Args/kwargs should be plain "scheduled" origin, not profile overrides
    assert orch.calls[0][0][1] == "scheduled"

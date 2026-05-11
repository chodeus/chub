"""Smoke tests for configuration loading and serialization."""

import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backend.util.scheduler as scheduler
from backend.modules.upgradinatorr import Upgradinatorr
from backend.util.config import (
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    SyncGDriveConfig,
    SyncGDriveToken,
    UpgradinatorrConfig,
    UpgradinatorrInstance,
    load_config,
    save_config,
)
from backend.util.scheduler import ChubScheduler


# --- Config Model Tests ---


def test_default_config_creates_valid_model():
    """ChubConfig with no args should produce a valid default."""
    config = ChubConfig()
    assert config.instances is not None
    assert isinstance(config.instances, InstancesConfig)


def test_instances_round_trip():
    """Instances written into config should survive model_dump and re-parse."""
    config = ChubConfig(
        instances=InstancesConfig(
            radarr={
                "radarr_main": InstanceDetail(url="http://radarr:7878", api="abc123")
            },
            sonarr={
                "sonarr_main": InstanceDetail(url="http://sonarr:8989", api="def456")
            },
            plex={"plex_main": InstanceDetail(url="http://plex:32400", api="token789")},
        )
    )

    dumped = config.model_dump(mode="python")

    # Verify structure
    assert "instances" in dumped
    assert "radarr" in dumped["instances"]
    assert "radarr_main" in dumped["instances"]["radarr"]
    assert dumped["instances"]["radarr"]["radarr_main"]["url"] == "http://radarr:7878"
    assert dumped["instances"]["radarr"]["radarr_main"]["api"] == "abc123"

    # Re-parse should work
    reparsed = ChubConfig.model_validate(dumped)
    assert reparsed.instances.radarr["radarr_main"].url == "http://radarr:7878"


def test_config_section_extraction():
    """Simulates GET /api/config?section=instances response building."""
    config = ChubConfig(
        instances=InstancesConfig(
            radarr={"r1": InstanceDetail(url="http://r1:7878", api="key1")},
        )
    )

    data = config.model_dump(mode="python")
    section = "instances"
    response_data = {section: data[section]}

    # Frontend expects: response.data.instances
    assert "instances" in response_data
    assert "radarr" in response_data["instances"]
    assert "r1" in response_data["instances"]["radarr"]


def test_empty_instances_config():
    """Empty instances config should still serialize to proper structure."""
    config = ChubConfig()
    dumped = config.model_dump(mode="python")

    assert dumped["instances"]["radarr"] == {}
    assert dumped["instances"]["sonarr"] == {}
    assert dumped["instances"]["plex"] == {}


def test_missing_config_path_returns_default_model(tmp_path):
    """Fresh installs should be able to boot before config.yml exists."""
    config_path = tmp_path / "missing" / "config.yml"

    config = load_config(str(config_path))

    assert isinstance(config, ChubConfig)
    assert config.auth.username == ""


def test_save_config_creates_config_directory(tmp_path):
    """First-run auth setup can save config.yml into an empty config mount."""
    config_path = tmp_path / "new-config-dir" / "config.yml"

    save_config(ChubConfig(), str(config_path))

    assert config_path.exists()


# --- GDrive Token Tests ---


def test_gdrive_token_as_pydantic_model():
    """Token as SyncGDriveToken should serialize correctly."""
    config = SyncGDriveConfig(
        token=SyncGDriveToken(
            access_token="ya29.test",
            token_type="Bearer",
            refresh_token="1//refresh",
            expiry="2024-01-01T00:00:00Z",
        )
    )

    # Should have model_dump
    assert hasattr(config.token, "model_dump")
    token_dict = config.token.model_dump()
    assert token_dict["access_token"] == "ya29.test"

    # json.dumps should work on model_dump output
    serialized = json.dumps(token_dict)
    assert "ya29.test" in serialized


def test_gdrive_token_as_string():
    """Token as JSON string should be passable directly to rclone."""
    token_json = '{"access_token":"ya29.test","token_type":"Bearer","refresh_token":"1//ref","expiry":"2024-01-01T00:00:00Z"}'
    config = SyncGDriveConfig(token=token_json)

    assert isinstance(config.token, str)

    # The fix: string tokens should pass through directly, not go through dict()
    if isinstance(config.token, str):
        # This is what the fixed code does
        result = config.token
    elif hasattr(config.token, "model_dump"):
        result = json.dumps(config.token.model_dump())
    else:
        result = json.dumps(dict(config.token))

    parsed = json.loads(result)
    assert parsed["access_token"] == "ya29.test"


def test_gdrive_token_as_empty_string():
    """Empty string token should be falsy."""
    config = SyncGDriveConfig(token="")
    assert not config.token


def test_gdrive_token_as_none():
    """None token should be falsy."""
    config = SyncGDriveConfig(token=None)
    assert not config.token


def test_gdrive_token_as_dict_from_yaml():
    """Token loaded from YAML as a dict should parse into SyncGDriveToken."""
    raw = {
        "token": {
            "access_token": "ya29.test",
            "token_type": "Bearer",
            "refresh_token": "1//ref",
            "expiry": "2024-01-01T00:00:00Z",
        }
    }
    config = SyncGDriveConfig.model_validate(raw)

    # Pydantic should coerce the dict into SyncGDriveToken
    assert hasattr(config.token, "model_dump")
    assert config.token.access_token == "ya29.test"


# --- Scheduler Format Tests ---


class MondayMorning(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2024, 5, 6, 9, 0, tzinfo=tz)


def test_weekly_schedule_accepts_ui_comma_day_format(monkeypatch):
    """Schedules saved by the UI as Mon,Fri@09:00 should fire."""
    monkeypatch.setattr(scheduler, "datetime", MondayMorning)

    assert scheduler.check_schedule("labelarr", "weekly(Mon,Fri@09:00)", None)


def test_weekly_schedule_accepts_canonical_pipe_format(monkeypatch):
    """Canonical weekly schedules use one day/time entry per selected day."""
    monkeypatch.setattr(scheduler, "datetime", MondayMorning)

    assert scheduler.check_schedule(
        "labelarr", "weekly(monday@09:00|friday@09:00)", None
    )


def test_monthly_schedule_accepts_multiple_days(monkeypatch):
    """Monthly schedules can include multiple selected month days."""
    monkeypatch.setattr(scheduler, "datetime", MondayMorning)

    assert scheduler.check_schedule("poster_renamerr", "monthly(1,6,15@09:00)", None)
    assert scheduler.check_schedule(
        "poster_renamerr", "monthly(1@09:00|6@09:00|15@09:00)", None
    )


# --- Upgradinatorr Profile / Tag Tests ---


class StubLogger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def log_outro(self):
        pass

    def get_adapter(self, *_args, **_kwargs):
        return self


def make_upgradinatorr(dry_run=True):
    module = object.__new__(Upgradinatorr)
    module._cancel_event = None
    module.logger = StubLogger()
    module.config = SimpleNamespace(dry_run=dry_run)
    return module


def upgradinatorr_media_item(tags):
    return {
        "title": "Movie",
        "year": 2024,
        "media_id": 7,
        "monitored": True,
        "status": "released",
        "seasons": None,
        "tags": tags,
    }


class FakeARR:
    instance_name = "radarr"
    instance_type = "Radarr"

    def __init__(self, media_batches):
        self.media_batches = list(media_batches)
        self.remove_calls = []
        self.search_calls = []
        self.add_calls = []

    def get_all_media(self, *args, **kwargs):
        if len(self.media_batches) > 1:
            return self.media_batches.pop(0)
        return self.media_batches[0]

    def get_tag_id_from_name(self, name):
        return {"checked": 1, "ignore": 2}[name]

    def remove_tags(self, media_ids, tag_id):
        self.remove_calls.append((media_ids, tag_id))

    def search_media(self, media_id):
        self.search_calls.append(media_id)
        return {"id": 99}

    def wait_for_command(self, command_id):
        return True

    def add_tags(self, media_id, tag_id):
        self.add_calls.append((media_id, tag_id))

    def get_queue(self):
        return {"records": []}


def test_upgradinatorr_filter_skips_checked_tag_name():
    module = make_upgradinatorr()

    result = module.filter_media(
        [upgradinatorr_media_item(["checked"])], "checked", "ignore", 10, 0
    )

    assert result == []


def test_upgradinatorr_filter_skips_ignore_tag_name():
    module = make_upgradinatorr()

    result = module.filter_media(
        [upgradinatorr_media_item(["ignore"])], "checked", "ignore", 10, 0
    )

    assert result == []


def test_upgradinatorr_unattended_dry_run_does_not_remove_tags():
    module = make_upgradinatorr(dry_run=True)
    app = FakeARR([[upgradinatorr_media_item(["checked"])]])

    result = module.process_instance(
        "radarr",
        SimpleNamespace(
            count=10,
            tag_name="checked",
            ignore_tag="ignore",
            unattended=True,
            season_monitored_threshold=0,
            search_mode="upgrade",
        ),
        app,
    )

    assert app.remove_calls == []
    assert result["tagged_count"] == 1
    assert result["data"] == []


def test_upgradinatorr_unattended_resets_checked_tag_then_processes_next_cycle():
    module = make_upgradinatorr(dry_run=False)
    app = FakeARR([[upgradinatorr_media_item(["checked"])], [upgradinatorr_media_item([])]])

    result = module.process_instance(
        "radarr",
        SimpleNamespace(
            count=10,
            tag_name="checked",
            ignore_tag="ignore",
            unattended=True,
            season_monitored_threshold=0,
            search_mode="upgrade",
        ),
        app,
    )

    assert app.remove_calls == [([7], 1)]
    assert app.search_calls == [7]
    assert app.add_calls == [(7, 1)]
    assert result["data"][0]["media_id"] == 7


def test_upgradinatorr_run_skips_disabled_profiles(monkeypatch):
    calls = []

    def fake_create_arr_client(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "backend.modules.upgradinatorr.create_arr_client", fake_create_arr_client
    )

    module = object.__new__(Upgradinatorr)
    module._cancel_event = None
    module.logger = StubLogger()
    module.config = UpgradinatorrConfig(
        instances_list=[
            UpgradinatorrInstance(
                enabled=False,
                instance="radarr_main",
                count=10,
                tag_name="checked",
            )
        ]
    )
    module.full_config = ChubConfig(
        instances=InstancesConfig(
            radarr={
                "radarr_main": InstanceDetail(url="http://radarr:7878", api="key")
            }
        ),
        upgradinatorr=module.config,
    )

    module.run()

    assert calls == []


class MondayNine(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2024, 5, 6, 9, 0, tzinfo=tz)


class Profile(SimpleNamespace):
    def model_dump(self, mode="python"):
        return dict(vars(self))


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def get_module_status(self, module_name):
        return {"running": False}

    def run_module_async(self, module_name, origin="scheduled", overrides=None):
        self.calls.append((module_name, origin, overrides))
        return {"success": True, "data": {"job_id": 123}}


def test_scheduler_enqueues_due_upgradinatorr_profile(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", MondayNine)
    config = SimpleNamespace(
        schedule={},
        upgradinatorr=SimpleNamespace(
            instances_list=[
                Profile(
                    label="Main Radarr",
                    enabled=True,
                    schedule="daily(09:00)",
                    instance="radarr_main",
                    count=10,
                    tag_name="checked",
                    ignore_tag="ignore",
                    unattended=False,
                    search_mode="upgrade",
                )
            ]
        ),
    )
    orchestrator = FakeOrchestrator()
    chub_scheduler = ChubScheduler(config, logger=None, module_orchestrator=orchestrator)

    chub_scheduler._tick(config.schedule)

    assert orchestrator.calls == [
        (
            "upgradinatorr",
            "scheduled:upgradinatorr_profiles",
            {
                "instances_list": [
                    {
                        "label": "Main Radarr",
                        "enabled": True,
                        "schedule": "daily(09:00)",
                        "instance": "radarr_main",
                        "count": 10,
                        "tag_name": "checked",
                        "ignore_tag": "ignore",
                        "unattended": False,
                        "search_mode": "upgrade",
                    }
                ]
            },
        )
    ]

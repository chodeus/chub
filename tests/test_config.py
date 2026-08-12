"""Smoke tests for configuration loading and serialization."""

import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import yaml
from pydantic import ValidationError

from backend.util import scheduler
from backend.modules.upgradinatorr import Upgradinatorr
from backend.util.arr import LidarrClient
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


def test_asset_renamerr_defaults():
    """AssetRenamerrConfig defaults are sane and the poster_renamerr chain flag
    exists."""
    config = ChubConfig()
    ar = config.asset_renamerr
    assert ar.sources == ["local", "fanart"]
    # defaults to the two types that work on BOTH apply methods
    assert ar.asset_types == ["logo", "background"]
    assert ar.apply_method == "kometa"
    assert config.poster_renamerr.run_asset_renamerr is False
    # notifications now default to an empty destinations list
    assert config.notifications.destinations == []


def test_poster_renamerr_music_defaults():
    """Music (Lidarr) artwork options default to off / local-only and the
    config round-trips them."""
    pr = ChubConfig().poster_renamerr
    assert pr.music_lock_artist_art is False
    assert pr.music_lma_sidecars is False
    assert pr.music_source_dirs == []

    loaded = ChubConfig(
        poster_renamerr={
            "music_lock_artist_art": True,
            "music_lma_sidecars": True,
            "music_source_dirs": ["/music/art"],
        }
    )
    assert loaded.poster_renamerr.music_lock_artist_art is True
    assert loaded.poster_renamerr.music_lma_sidecars is True
    assert loaded.poster_renamerr.music_source_dirs == ["/music/art"]


def test_asset_renamerr_banner_direct_combo_loads():
    """banner + plex apply must NOT be a hard validation error — the config
    has to stay loadable while a user toggles apply_method (the incompatibility
    is handled at runtime with a skip + warning). Also confirms the legacy
    "direct" value is coerced to the renamed "plex" value."""
    config = ChubConfig.model_validate(
        {
            "asset_renamerr": {
                "apply_method": "direct",
                "asset_types": ["banner", "logo"],
            }
        }
    )
    assert config.asset_renamerr.apply_method == "plex"
    assert "banner" in config.asset_renamerr.asset_types


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


def test_load_config_caches_until_the_file_changes(tmp_path, monkeypatch):
    """Repeat loads come from cache; a rewrite is picked up on the next load."""
    config_path = str(tmp_path / "config.yml")
    config = ChubConfig()
    config.auth.username = "first"
    save_config(config, config_path)

    parses = []
    # Same module object backend.util.config calls yaml.safe_load on.
    real_safe_load = yaml.safe_load

    def _counting_safe_load(stream):
        """Count each parse, then delegate to the real yaml.safe_load."""
        parses.append(1)
        return real_safe_load(stream)

    monkeypatch.setattr(yaml, "safe_load", _counting_safe_load)

    assert load_config(config_path).auth.username == "first"
    assert load_config(config_path).auth.username == "first"
    assert len(parses) == 1

    config.auth.username = "second"
    save_config(config, config_path)
    assert load_config(config_path).auth.username == "second"


def test_load_config_does_not_share_mutable_state(tmp_path):
    """Callers mutate what load_config returns before saving — never the cache."""
    config_path = str(tmp_path / "config.yml")
    save_config(ChubConfig(), config_path)

    first = load_config(config_path)
    first.auth.username = "never-saved"
    first.general.disabled_modules.append("nohl")

    second = load_config(config_path)
    assert second.auth.username == ""
    assert second.general.disabled_modules == []


def test_legacy_notifications_auto_heal_on_load(tmp_path):
    """An existing per-module notifications config must auto-migrate to the
    per-destination shape on load AND be rewritten to disk, with the original
    preserved as a legacy backup."""
    config_path = tmp_path / "config.yml"
    legacy = {
        "general": {"log_level": "info"},
        "notifications": {
            "poster_renamerr": {
                "discord": {
                    "webhook": "https://discord.com/api/webhooks/1/a",
                    "bot_name": "CHUB",
                }
            },
            "asset_renamerr": {
                "discord": {"webhook": "https://discord.com/api/webhooks/1/a"}
            },
            "main": {"discord": {"webhook": "https://discord.com/api/webhooks/9/err"}},
        },
    }
    config_path.write_text(yaml.safe_dump(legacy, sort_keys=False))

    config = load_config(str(config_path))

    # In-memory model is the new shape.
    dests = config.notifications.destinations
    assert dests, "expected migrated destinations"
    shared = [d for d in dests if "webhooks/1/a" in (d.config.get("webhook") or "")]
    assert len(shared) == 1
    assert sorted(shared[0].modules) == ["asset_renamerr", "poster_renamerr"]
    assert shared[0].events.success is True
    errd = [d for d in dests if "webhooks/9/err" in (d.config.get("webhook") or "")]
    assert errd and errd[0].events.failure is True and errd[0].modules == ["__ALL__"]

    # File on disk was rewritten to the new shape...
    persisted = yaml.safe_load(config_path.read_text())
    assert set(persisted["notifications"].keys()) == {"destinations"}

    # ...and the original was preserved as a legacy backup.
    backups = list(tmp_path.glob("config.yml.legacy-*.yml"))
    assert backups, "expected a legacy backup file"

    # Reloading the healed file is a no-op (no further migration).
    reloaded = load_config(str(config_path))
    assert len(reloaded.notifications.destinations) == len(dests)
    assert len(list(tmp_path.glob("config.yml.legacy-*.yml"))) == len(backups)


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
    def __init__(self):
        self.warnings = []

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        self.warnings.append(" ".join(str(arg) for arg in args))

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

    def wait_for_command_result(self, command_id, label=""):
        return "completed"

    def count_queued_commands(self, _names):
        return 0

    def add_tags(self, media_id, tag_id):
        self.add_calls.append((media_id, tag_id))

    def get_queue(self):
        return {"records": []}


class FakeFailingARR(FakeARR):
    def wait_for_command(self, command_id):
        return False

    def wait_for_command_result(self, command_id, label=""):
        return "failed"


class FakeQueueARR(FakeARR):
    def get_queue(self):
        return {
            "records": [
                {
                    "downloadId": "download-7",
                    "movieId": 7,
                    "title": "Movie.2024.1080p.WEB-DL",
                    "customFormatScore": 7777,
                }
            ]
        }


def test_upgradinatorr_instance_count_mode_defaults_to_series_artist():
    inst = UpgradinatorrInstance()
    assert inst.count_mode == "series_artist"


def test_upgradinatorr_instance_count_mode_accepts_season_album():
    inst = UpgradinatorrInstance(count_mode="season_album")
    assert inst.count_mode == "season_album"


class CaptureLidarrClient(LidarrClient):
    def make_get_request(self, endpoint, headers=None, params=None):
        self.captured_request = {
            "endpoint": endpoint,
            "headers": headers,
            "params": params,
        }
        return {"records": [], "totalRecords": 0}


def test_lidarr_wanted_requests_use_album_safe_params():
    client = object.__new__(CaptureLidarrClient)
    client.url = "http://lidarr:8686"

    client.get_wanted_missing(page=3, page_size=50)

    assert client.captured_request == {
        "endpoint": "http://lidarr:8686/api/v1/wanted/missing",
        "headers": None,
        "params": {
            "page": 3,
            "pageSize": 50,
            "includeArtist": "true",
            "monitored": "true",
        },
    }
    assert "sortKey" not in client.captured_request["params"]

    client.get_wanted_cutoff(page=2, page_size=25)

    assert client.captured_request == {
        "endpoint": "http://lidarr:8686/api/v1/wanted/cutoff",
        "headers": None,
        "params": {
            "page": 2,
            "pageSize": 25,
            "includeArtist": "true",
            "monitored": "true",
        },
    }
    assert "sortKey" not in client.captured_request["params"]


class FakeLidarrWantedApp:
    def get_all_tags(self):
        return [{"id": 1, "label": "checked"}]


def test_upgradinatorr_lidarr_wanted_records_group_by_artist():
    module = make_upgradinatorr()
    records = [
        {
            "id": 101,
            "title": "First Album",
            "foreignAlbumId": "mb-album-1",
            "monitored": True,
            "artist": {
                "id": 21,
                "artistName": "The Artist",
                "monitored": True,
                "status": "continuing",
                "tags": [],
                "path": "/music/The Artist",
            },
        },
        {
            "id": 102,
            "title": "Second Album",
            "foreignAlbumId": "mb-album-2",
            "monitored": True,
            "artist": {
                "id": 21,
                "artistName": "The Artist",
                "monitored": True,
                "status": "continuing",
                "tags": [],
                "path": "/music/The Artist",
            },
        },
    ]

    result = module._convert_wanted_to_media_dict(
        records, "lidarr", FakeLidarrWantedApp()
    )

    assert len(result) == 1
    assert result[0]["media_id"] == 21
    assert result[0]["title"] == "The Artist"
    assert result[0]["seasons"] == [
        {
            "season_number": 0,
            "album_id": 101,
            "album_title": "First Album",
            "foreign_album_id": "mb-album-1",
            "monitored": True,
            "episode_data": [],
        },
        {
            "season_number": 1,
            "album_id": 102,
            "album_title": "Second Album",
            "foreign_album_id": "mb-album-2",
            "monitored": True,
            "episode_data": [],
        },
    ]


class FailingWantedApp:
    instance_name = "lidarr"

    def get_wanted_missing(self, page=1, page_size=100):
        return None


def test_upgradinatorr_wanted_fetch_failure_is_not_empty_list():
    module = make_upgradinatorr()

    result = module._get_all_wanted(FailingWantedApp(), "missing")

    assert result is None
    assert any(
        "Failed to fetch missing page 1" in msg for msg in module.logger.warnings
    )


class FakeProgress:
    """In-memory stand-in for UpgradinatorrProgress."""

    def __init__(self):
        self._rows = {}  # (instance, media_id) -> set[str]
        self.cleared_media = []
        self.cleared_instances = []

    def get_processed_children(self, instance_name, media_id):
        return set(self._rows.get((instance_name, media_id), set()))

    def record_processed_child(self, instance_name, media_id, child_id):
        self._rows.setdefault((instance_name, media_id), set()).add(str(child_id))

    def clear_for_media(self, instance_name, media_id):
        self._rows.pop((instance_name, media_id), None)
        self.cleared_media.append((instance_name, media_id))

    def clear_for_instance(self, instance_name):
        for key in list(self._rows):
            if key[0] == instance_name:
                self._rows.pop(key)
        self.cleared_instances.append(instance_name)


class FakeSonarrApp:
    instance_name = "sonarr_main"
    instance_type = "Sonarr"

    def __init__(self):
        self.season_searches = []
        self.tag_calls = []

    def search_season(self, media_id, season_number):
        self.season_searches.append((media_id, season_number))
        return {"id": 42}

    def wait_for_command(self, _cmd_id):
        return True

    def wait_for_command_result(self, _cmd_id, label=""):
        return "completed"

    def count_queued_commands(self, _names):
        return 0

    def add_tags(self, media_id, tag_id):
        self.tag_calls.append((media_id, tag_id))


class FakeSonarrHistoryApp(FakeSonarrApp):
    def __init__(self):
        super().__init__()
        self.grab_history = {}

    def search_season(self, media_id, season_number):
        response = super().search_season(media_id, season_number)
        self.grab_history[season_number] = [
            {
                "id": season_number,
                "downloadId": f"download-{season_number}",
                "sourceTitle": f"Gen.V.S{season_number:02}.1080p.WEB-DL",
                "customFormatScore": 8000 + season_number,
            }
        ]
        return response

    def get_season_grab_history(self, _media_id, season_number):
        return {"records": self.grab_history.get(season_number, [])}


class FakeFailingSonarrApp(FakeSonarrApp):
    def wait_for_command(self, _cmd_id):
        return False

    def wait_for_command_result(self, _cmd_id, label=""):
        return "failed"


class FakeLidarrApp:
    instance_name = "lidarr_main"
    instance_type = "Lidarr"

    def __init__(self):
        self.album_searches = []
        self.tag_calls = []

    def search_album(self, album_id):
        self.album_searches.append(album_id)
        return {"id": 42}

    def wait_for_command(self, _cmd_id):
        return True

    def wait_for_command_result(self, _cmd_id, label=""):
        return "completed"

    def count_queued_commands(self, _names):
        return 0

    def add_tags(self, media_id, tag_id):
        self.tag_calls.append((media_id, tag_id))


class FakeLidarrHistoryApp(FakeLidarrApp):
    def __init__(self):
        super().__init__()
        self.grab_history = {}

    def search_album(self, album_id):
        response = super().search_album(album_id)
        self.grab_history[album_id] = [
            {
                "id": album_id,
                "downloadId": f"download-{album_id}",
                "sourceTitle": f"Artist.Album.{album_id}.FLAC",
                "customFormatScore": 9000 + album_id,
                "eventType": "grabbed",
            }
        ]
        return response

    def get_album_grab_history(self, album_id):
        return {"records": self.grab_history.get(album_id, [])}


class FakeFailingLidarrApp(FakeLidarrApp):
    def wait_for_command(self, _cmd_id):
        return False

    def wait_for_command_result(self, _cmd_id, label=""):
        return "failed"


def _sonarr_item():
    return {
        "title": "Show",
        "year": 2024,
        "media_id": 11,
        "monitored": True,
        "status": "continuing",
        "tags": [],
        "seasons": [
            {"season_number": 1, "monitored": True, "episode_data": []},
            {"season_number": 2, "monitored": True, "episode_data": []},
            {"season_number": 3, "monitored": True, "episode_data": []},
        ],
    }


def _lidarr_item():
    return {
        "title": "Artist",
        "year": 2024,
        "media_id": 21,
        "monitored": True,
        "status": "continuing",
        "tags": [],
        "seasons": [
            {
                "season_number": 0,
                "album_id": 101,
                "album_title": "A",
                "monitored": True,
                "episode_data": [],
            },
            {
                "season_number": 1,
                "album_id": 102,
                "album_title": "B",
                "monitored": True,
                "episode_data": [],
            },
            {
                "season_number": 2,
                "album_id": 103,
                "album_title": "C",
                "monitored": True,
                "episode_data": [],
            },
        ],
    }


def test_upgradinatorr_granular_sonarr_resumes_across_runs():
    module = make_upgradinatorr(dry_run=False)
    app = FakeSonarrApp()
    progress = FakeProgress()
    item = _sonarr_item()

    # Run 1: budget = 2 → search seasons 1, 2, no tag, progress records both.
    new_count, hit = module._process_sonarr_item(
        item,
        app,
        checked_tag_id=99,
        count=2,
        granular=True,
        progress_db=progress,
        search_count=0,
    )
    assert hit is True
    assert new_count == 2
    assert app.season_searches == [(11, 1), (11, 2)]
    assert app.tag_calls == []
    assert progress.get_processed_children("sonarr_main", 11) == {"1", "2"}

    # Run 2: only season 3 remains → 1 search, tag added, progress cleared.
    new_count, hit = module._process_sonarr_item(
        item,
        app,
        checked_tag_id=99,
        count=2,
        granular=True,
        progress_db=progress,
        search_count=0,
    )
    assert hit is False
    assert new_count == 1
    assert app.season_searches == [(11, 1), (11, 2), (11, 3)]
    assert app.tag_calls == [(11, 99)]
    assert progress.get_processed_children("sonarr_main", 11) == set()


def test_upgradinatorr_granular_sonarr_skips_already_done_parent():
    module = make_upgradinatorr(dry_run=False)
    app = FakeSonarrApp()
    progress = FakeProgress()
    progress.record_processed_child("sonarr_main", 11, "1")
    progress.record_processed_child("sonarr_main", 11, "2")
    progress.record_processed_child("sonarr_main", 11, "3")

    new_count, hit = module._process_sonarr_item(
        _sonarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=True,
        progress_db=progress,
        search_count=0,
    )
    # No budget consumed but parent finalized.
    assert hit is False
    assert new_count == 0
    assert app.season_searches == []
    assert app.tag_calls == [(11, 99)]
    assert progress.get_processed_children("sonarr_main", 11) == set()


def test_upgradinatorr_legacy_sonarr_tags_once_and_clears_stale_progress():
    module = make_upgradinatorr(dry_run=False)
    app = FakeSonarrApp()
    progress = FakeProgress()
    progress.record_processed_child("sonarr_main", 11, "1")

    new_count, hit = module._process_sonarr_item(
        _sonarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=False,
        progress_db=progress,
        search_count=0,
    )
    # All monitored seasons searched, parent tagged once, stale row wiped.
    assert hit is False
    assert new_count == 1
    assert app.season_searches == [(11, 1), (11, 2), (11, 3)]
    assert app.tag_calls == [(11, 99)]
    assert progress.get_processed_children("sonarr_main", 11) == set()


def test_upgradinatorr_sonarr_captures_all_grabbed_seasons():
    module = make_upgradinatorr(dry_run=False)
    app = FakeSonarrHistoryApp()
    grabbed = {}
    stats = {}

    new_count, hit = module._process_sonarr_item(
        _sonarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=False,
        progress_db=None,
        search_count=0,
        grabbed_downloads=grabbed,
        search_stats=stats,
    )

    assert hit is False
    assert new_count == 1
    assert stats == {
        "searches_attempted": 3,
        "searches_succeeded": 3,
    }
    assert [download["download"] for download in grabbed[11]] == [
        "Gen.V.S01.1080p.WEB-DL",
        "Gen.V.S02.1080p.WEB-DL",
        "Gen.V.S03.1080p.WEB-DL",
    ]


def test_upgradinatorr_sonarr_failure_does_not_tag_or_record_progress():
    module = make_upgradinatorr(dry_run=False)
    app = FakeFailingSonarrApp()
    progress = FakeProgress()
    failed = {}
    stats = {}

    new_count, hit = module._process_sonarr_item(
        _sonarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=True,
        progress_db=progress,
        search_count=0,
        failed_searches=failed,
        search_stats=stats,
    )

    assert hit is False
    assert new_count == 3
    assert app.tag_calls == []
    assert progress.get_processed_children("sonarr_main", 11) == set()
    assert failed[11] == ["Season 1", "Season 2", "Season 3"]
    assert stats == {
        "searches_attempted": 3,
        "searches_failed": 3,
    }


def test_upgradinatorr_granular_lidarr_resumes_across_runs():
    module = make_upgradinatorr(dry_run=False)
    app = FakeLidarrApp()
    progress = FakeProgress()
    item = _lidarr_item()

    new_count, hit = module._process_lidarr_item(
        item,
        app,
        checked_tag_id=99,
        count=2,
        granular=True,
        progress_db=progress,
        search_count=0,
    )
    assert hit is True
    assert new_count == 2
    assert app.album_searches == [101, 102]
    assert app.tag_calls == []
    assert progress.get_processed_children("lidarr_main", 21) == {"101", "102"}

    new_count, hit = module._process_lidarr_item(
        item,
        app,
        checked_tag_id=99,
        count=2,
        granular=True,
        progress_db=progress,
        search_count=0,
    )
    assert hit is False
    assert new_count == 1
    assert app.album_searches == [101, 102, 103]
    assert app.tag_calls == [(21, 99)]
    assert progress.get_processed_children("lidarr_main", 21) == set()


def test_upgradinatorr_lidarr_captures_all_grabbed_albums():
    module = make_upgradinatorr(dry_run=False)
    app = FakeLidarrHistoryApp()
    grabbed = {}
    stats = {}

    new_count, hit = module._process_lidarr_item(
        _lidarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=False,
        progress_db=None,
        search_count=0,
        grabbed_downloads=grabbed,
        search_stats=stats,
    )

    assert hit is False
    assert new_count == 1
    assert [download["download"] for download in grabbed[21]] == [
        "Artist.Album.101.FLAC",
        "Artist.Album.102.FLAC",
        "Artist.Album.103.FLAC",
    ]
    assert stats == {
        "searches_attempted": 3,
        "searches_succeeded": 3,
    }


class FakeLeakyLidarrApp(FakeLidarrHistoryApp):
    """Mimics Lidarr's /history when the scope filter is ignored: every call
    returns the whole library's recent grabs, not just the album's. A manual
    download for an unrelated artist lands mid-run, so it is absent from the
    "before" snapshot and present in the "after" one — which is what made it
    look like a new grab for the album being searched."""

    UNRELATED = {
        "id": 9001,
        "downloadId": "manual-pantera",
        "sourceTitle": (
            "Pantera - Reinventing the Steel (2000) [Album] "
            "[20th Anniversary Edition 2020] [FLAC 24bit Lossless / WEB]"
        ),
        "customFormatScore": 6,
        "eventType": "grabbed",
        "artistId": 189,
        "albumId": 358,
    }

    def __init__(self):
        super().__init__()
        self.history_calls = 0

    def search_album(self, album_id):
        response = FakeLidarrApp.search_album(self, album_id)
        self.grab_history[album_id] = [
            {
                "id": album_id,
                "downloadId": f"download-{album_id}",
                "sourceTitle": f"Artist.Album.{album_id}.FLAC",
                "customFormatScore": 9000 + album_id,
                "eventType": "grabbed",
                "artistId": 21,
                "albumId": album_id,
            }
        ]
        return response

    def get_album_grab_history(self, album_id):
        self.history_calls += 1
        records = list(self.grab_history.get(album_id, []))
        # Call 1 is the first album's "before" snapshot; the manual grab appears
        # from the following call onward.
        if self.history_calls > 1:
            records.insert(0, self.UNRELATED)
        return {"records": records}


def test_upgradinatorr_ignores_grabs_belonging_to_other_media():
    module = make_upgradinatorr(dry_run=False)
    app = FakeLeakyLidarrApp()
    grabbed = {}

    module._process_lidarr_item(
        _lidarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=False,
        progress_db=None,
        search_count=0,
        grabbed_downloads=grabbed,
    )

    captured = [download["download"] for download in grabbed[21]]
    assert captured == [
        "Artist.Album.101.FLAC",
        "Artist.Album.102.FLAC",
        "Artist.Album.103.FLAC",
    ]
    assert not any("Pantera" in title for title in captured)


def test_upgradinatorr_scope_check_keeps_records_without_ids():
    """An id the *arr doesn't serialize means "can't tell" — the record is kept
    rather than silently dropped from the report."""
    module = make_upgradinatorr(dry_run=False)

    assert module._record_in_scope({"sourceTitle": "x"}, "lidarr", 21, 101) is True
    assert module._record_in_scope({"artistId": 21}, "lidarr", 21, None) is True
    assert module._record_in_scope({"artistId": 189}, "lidarr", 21, None) is False
    assert module._record_in_scope({"albumId": 358}, "lidarr", 21, 101) is False
    assert module._record_in_scope({"seriesId": 11}, "sonarr", 11, None) is True
    assert module._record_in_scope({"movieId": 5}, "radarr", 7, None) is False


def test_upgradinatorr_lidarr_failure_does_not_tag_or_record_progress():
    module = make_upgradinatorr(dry_run=False)
    app = FakeFailingLidarrApp()
    progress = FakeProgress()
    failed = {}
    stats = {}

    new_count, hit = module._process_lidarr_item(
        _lidarr_item(),
        app,
        checked_tag_id=99,
        count=5,
        granular=True,
        progress_db=progress,
        search_count=0,
        failed_searches=failed,
        search_stats=stats,
    )

    assert hit is False
    assert new_count == 3
    assert app.tag_calls == []
    assert progress.get_processed_children("lidarr_main", 21) == set()
    assert failed[21] == ["Album A", "Album B", "Album C"]
    assert stats == {
        "searches_attempted": 3,
        "searches_failed": 3,
    }


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
    app = FakeARR(
        [[upgradinatorr_media_item(["checked"])], [upgradinatorr_media_item([])]]
    )

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


def test_upgradinatorr_radarr_failure_does_not_tag():
    module = make_upgradinatorr(dry_run=False)
    app = FakeFailingARR([[upgradinatorr_media_item([])]])

    result = module.process_instance(
        "radarr",
        SimpleNamespace(
            count=10,
            tag_name="checked",
            ignore_tag="ignore",
            unattended=False,
            season_monitored_threshold=0,
            search_mode="upgrade",
        ),
        app,
    )

    assert app.search_calls == [7]
    assert app.add_calls == []
    assert result["searches_attempted"] == 1
    assert result["searches_failed"] == 1
    assert result["data"][0]["search_failures"] == ["Media search"]


def test_upgradinatorr_queue_fallback_still_reports_downloads():
    module = make_upgradinatorr(dry_run=False)
    app = FakeQueueARR([[upgradinatorr_media_item([])]])

    result = module.process_instance(
        "radarr",
        SimpleNamespace(
            count=10,
            tag_name="checked",
            ignore_tag="ignore",
            unattended=False,
            season_monitored_threshold=0,
            search_mode="upgrade",
        ),
        app,
    )

    assert app.add_calls == [(7, 1)]
    assert result["data"][0]["download"] == {"Movie.2024.1080p.WEB-DL": 7777}


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
            radarr={"radarr_main": InstanceDetail(url="http://radarr:7878", api="key")}
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
    chub_scheduler = ChubScheduler(
        config, logger=None, module_orchestrator=orchestrator
    )

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


def test_poster_renamerr_upload_delay_default_and_bounds():
    """upload_delay_ms throttle: off by default, accepts a configured value."""
    assert ChubConfig().poster_renamerr.upload_delay_ms == 0
    cfg = ChubConfig.model_validate({"poster_renamerr": {"upload_delay_ms": 50}})
    assert cfg.poster_renamerr.upload_delay_ms == 50


def test_poster_renamerr_action_type_validation():
    """Invalid action_type is rejected (was a silent no-op reported as success);
    valid values are case-normalized."""
    assert (
        ChubConfig.model_validate(
            {"poster_renamerr": {"action_type": "Hardlink"}}
        ).poster_renamerr.action_type
        == "hardlink"
    )
    with pytest.raises(ValidationError):
        ChubConfig.model_validate({"poster_renamerr": {"action_type": "mvoe"}})


def test_asset_renamerr_apply_method_and_action_type_validation():
    """apply_method accepts plex/kometa (legacy 'direct' aliases to 'plex',
    case-insensitively); invalid values no longer silently route to kometa."""
    # Legacy "direct" (any case) coerces to the renamed "plex" value.
    assert (
        ChubConfig.model_validate(
            {"asset_renamerr": {"apply_method": "DIRECT"}}
        ).asset_renamerr.apply_method
        == "plex"
    )
    assert (
        ChubConfig.model_validate(
            {"asset_renamerr": {"apply_method": "plex"}}
        ).asset_renamerr.apply_method
        == "plex"
    )
    assert (
        ChubConfig.model_validate(
            {"asset_renamerr": {"apply_method": "kometa"}}
        ).asset_renamerr.apply_method
        == "kometa"
    )
    with pytest.raises(ValidationError):
        ChubConfig.model_validate({"asset_renamerr": {"apply_method": "ftp"}})
    with pytest.raises(ValidationError):
        ChubConfig.model_validate({"asset_renamerr": {"action_type": "teleport"}})


def test_renameinatorr_count_coercion():
    """Numeric-string count coerces to int (no longer crashes range());
    empty string is the 'all' sentinel; garbage is rejected."""
    assert (
        ChubConfig.model_validate(
            {"renameinatorr": {"count": "50"}}
        ).renameinatorr.count
        == 50
    )
    assert (
        ChubConfig.model_validate({"renameinatorr": {"count": ""}}).renameinatorr.count
        == ""
    )
    assert ChubConfig().renameinatorr.count == 100
    with pytest.raises(ValidationError):
        ChubConfig.model_validate({"renameinatorr": {"count": "abc"}})


# ── First-run setup wizard backfill ──────────────────────────────────────────


def test_setup_backfill_used_config_missing_flag(tmp_path):
    """An existing/used install missing setup_completed is treated as done so
    upgraders never see the first-run wizard."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "auth": {"username": "admin", "password_hash": "x"},
                "instances": {"radarr": {"Main": {"url": "http://r", "api": "k"}}},
            }
        )
    )
    assert load_config(str(config_path)).general.setup_completed is True


def test_setup_backfill_tmdb_only_counts_as_used(tmp_path):
    """A TMDB key alone is enough to count an install as already set up."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump({"tmdb": {"apikey": "abc123"}}))
    assert load_config(str(config_path)).general.setup_completed is True


def test_setup_backfill_empty_config_is_not_completed(tmp_path):
    """A near-empty (fresh) config gets setup_completed=False → wizard shows."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump({"general": {"log_level": "info"}}))
    assert load_config(str(config_path)).general.setup_completed is False


def test_setup_explicit_value_respected(tmp_path):
    """An explicit setup_completed is never overridden by the backfill, even
    when the config otherwise looks used."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "general": {"setup_completed": False},
                "auth": {"username": "admin", "password_hash": "x"},
            }
        )
    )
    assert load_config(str(config_path)).general.setup_completed is False

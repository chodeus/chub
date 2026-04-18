"""Smoke tests for configuration loading and serialization."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.config import (
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    SyncGDriveConfig,
    SyncGDriveToken,
)


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
            radarr={"radarr_main": InstanceDetail(url="http://radarr:7878", api="abc123")},
            sonarr={"sonarr_main": InstanceDetail(url="http://sonarr:8989", api="def456")},
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

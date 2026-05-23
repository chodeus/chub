"""Tests for backend/util/config.py — secret redaction and round-trip helpers."""

import pytest

from backend.util.config import (
    REDACTED_PLACEHOLDER,
    ChubConfig,
    ConfigParseError,
    ConfigValidationError,
    format_validation_errors,
    load_config,
    redact_secrets,
    save_config,
    strip_redacted_placeholders,
)


# --- redact_secrets ---


def test_redact_secrets_replaces_api_keys():
    data = {"instances": {"radarr": {"main": {"url": "x", "api": "real-key"}}}}
    out = redact_secrets(data)
    assert out["instances"]["radarr"]["main"]["api"] == REDACTED_PLACEHOLDER
    assert out["instances"]["radarr"]["main"]["url"] == "x"


def test_redact_secrets_handles_password_hash():
    data = {"auth": {"username": "u", "password_hash": "$2b$12$hash"}}
    out = redact_secrets(data)
    assert out["auth"]["password_hash"] == REDACTED_PLACEHOLDER
    assert out["auth"]["username"] == "u"


def test_redact_secrets_does_not_redact_empty():
    """Empty strings shouldn't be replaced — only real values are redacted."""
    data = {"auth": {"jwt_secret": ""}}
    out = redact_secrets(data)
    assert out["auth"]["jwt_secret"] == ""


def test_redact_secrets_recurses_into_lists():
    data = {"items": [{"api": "k1"}, {"api": "k2"}]}
    out = redact_secrets(data)
    assert out["items"][0]["api"] == REDACTED_PLACEHOLDER
    assert out["items"][1]["api"] == REDACTED_PLACEHOLDER


def test_redact_secrets_is_immutable():
    data = {"api": "real"}
    redact_secrets(data)
    assert data["api"] == "real"  # original untouched


def test_redact_secrets_token_field():
    data = {"sync_gdrive": {"token": "ya29.real"}}
    out = redact_secrets(data)
    assert out["sync_gdrive"]["token"] == REDACTED_PLACEHOLDER


# --- strip_redacted_placeholders ---


def test_strip_placeholder_keeps_current_value():
    current = {"api": "real-key", "url": "http://r:7878"}
    incoming = {"api": REDACTED_PLACEHOLDER, "url": "http://new:7878"}
    merged = strip_redacted_placeholders(incoming, current)
    assert merged["api"] == "real-key"
    assert merged["url"] == "http://new:7878"


def test_strip_placeholder_nested():
    current = {"instances": {"radarr": {"main": {"api": "real"}}}}
    incoming = {"instances": {"radarr": {"main": {"api": REDACTED_PLACEHOLDER}}}}
    merged = strip_redacted_placeholders(incoming, current)
    assert merged["instances"]["radarr"]["main"]["api"] == "real"


def test_strip_placeholder_lets_real_changes_through():
    current = {"api": "old"}
    incoming = {"api": "new-real-value"}
    merged = strip_redacted_placeholders(incoming, current)
    assert merged["api"] == "new-real-value"


def test_strip_placeholder_preserves_unspecified_keys():
    current = {"a": 1, "b": 2}
    incoming = {"a": 99}
    merged = strip_redacted_placeholders(incoming, current)
    assert merged["a"] == 99
    assert merged["b"] == 2


# --- load_config / save_config error handling ---


def test_load_config_handles_invalid_yaml(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("not: valid: yaml: : :")
    with pytest.raises(ConfigParseError):
        load_config(str(path))


def test_load_config_empty_file_raises(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("")
    with pytest.raises(ConfigParseError):
        load_config(str(path))


def test_load_config_validation_error_for_wrong_type(tmp_path):
    path = tmp_path / "config.yml"
    # general.max_logs expects int, give string
    path.write_text("general:\n  max_logs: not_an_int\n")
    with pytest.raises(ConfigValidationError):
        load_config(str(path))


def test_general_config_rejects_negative_runtime_values(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        "general:\n"
        "  max_logs: -1\n"
        "  webhook_initial_delay: -1\n"
        "  webhook_retry_delay: -1\n"
        "  webhook_max_retries: -1\n"
    )

    with pytest.raises(ConfigValidationError):
        load_config(str(path))


def test_general_config_rejects_unknown_log_level(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("general:\n  log_level: verbose\n")

    with pytest.raises(ConfigValidationError):
        load_config(str(path))


def test_format_validation_errors_emits_one_line_per_field(tmp_path):
    """format_validation_errors should produce one humanized line per Pydantic error."""
    path = tmp_path / "config.yml"
    # Two distinct violations: max_logs wrong type, log_level out of allowed values
    path.write_text("general:\n  max_logs: not_an_int\n  log_level: verbose\n")
    try:
        load_config(str(path))
    except ConfigValidationError as e:
        lines = format_validation_errors(e.validation_error)
        assert len(lines) >= 2
        joined = "\n".join(lines)
        assert "general -> max_logs" in joined
        assert "general -> log_level" in joined
        # Got-input snippet present for scalar inputs
        assert "got:" in joined
    else:
        raise AssertionError("expected ConfigValidationError")


def test_format_validation_errors_mirrors_real_daps_failure_shape(tmp_path):
    """The legacy DAPS shape (unmatched_assets.instances containing a dict)
    must be migrated cleanly; this test exists so the formatter contract is
    exercised against a realistic structure the migrator now handles."""
    path = tmp_path / "config.yml"
    path.write_text(
        "unmatched_assets:\n"
        "  instances:\n"
        "    - radarr\n"
        "    - sonarr\n"
        "    - Plex:\n"
        "        library_names: [Movies]\n"
    )
    # Should now load cleanly because the migrator flattens the dict entry
    cfg = load_config(str(path))
    assert cfg.unmatched_assets.instances == ["radarr", "sonarr", "Plex"]


def test_general_config_normalizes_uppercase_log_level(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("general:\n  log_level: INFO\n")

    assert load_config(str(path)).general.log_level == "info"


def test_save_and_load_config_round_trip(tmp_path):
    path = tmp_path / "config.yml"
    config = ChubConfig()
    config.general.max_logs = 5
    config.auth.username = "tester"

    save_config(config, str(path))
    reloaded = load_config(str(path))
    assert reloaded.general.max_logs == 5
    assert reloaded.auth.username == "tester"

"""Tests for backend/util/version.py — manifest-driven versioning."""

import subprocess
from unittest.mock import MagicMock, patch

import backend.util.version as version_mod
from backend.util.version import _read_base_version, check_for_update, get_version


def test_read_base_version_returns_string():
    v = _read_base_version()
    assert isinstance(v, str) and v


def test_get_version_uses_ci_env(monkeypatch):
    monkeypatch.setenv("BUILD_NUMBER", "42")
    monkeypatch.setenv("BRANCH", "main")
    v = get_version()
    assert v.endswith(".main42")


def test_get_version_falls_back_to_git(monkeypatch):
    """Without CI envs, version reads from git."""
    monkeypatch.delenv("BUILD_NUMBER", raising=False)
    monkeypatch.delenv("BRANCH", raising=False)
    fake_outputs = iter([b"main\n", b"123\n"])

    def fake_check_output(*args, **kwargs):
        return next(fake_outputs)

    with patch.object(subprocess, "check_output", side_effect=fake_check_output):
        v = get_version()
    assert v.endswith(".main123")


def test_get_version_falls_back_to_base_when_git_fails(monkeypatch):
    monkeypatch.delenv("BUILD_NUMBER", raising=False)
    monkeypatch.delenv("BRANCH", raising=False)

    def boom(*args, **kwargs):
        raise OSError("no git")

    with patch.object(subprocess, "check_output", side_effect=boom):
        v = get_version()
    # No suffix appended on git failure
    assert v == _read_base_version()


def test_check_for_update_reports_available():
    with patch.object(version_mod, "get_version", return_value="3.0.0.main50"):
        with patch.object(
            version_mod,
            "_check_remote_version",
            return_value=("3.0.0.main55", 55, True),
        ):
            result = check_for_update(MagicMock())
    assert result["update_available"] is True
    assert result["local_version"] == "3.0.0.main50"
    assert result["remote_version"] == "3.0.0.main55"
    assert result["branch"] == "main"
    assert result["checked"] is True


def test_check_for_update_handles_network_failure():
    with patch.object(version_mod, "get_version", return_value="3.0.0.develop12"):
        with patch.object(
            version_mod, "_check_remote_version", return_value=(None, None, False)
        ):
            result = check_for_update(MagicMock())
    assert result["update_available"] is False
    assert result["checked"] is False
    assert result["branch"] == "develop"

"""Tests for backend/util/version.py — manifest-driven versioning."""

import subprocess
from unittest.mock import patch

from backend.util.version import _read_base_version, get_version


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

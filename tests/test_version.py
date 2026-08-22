"""Tests for backend/util/version.py — manifest-driven versioning."""

import json
import subprocess
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest

from backend.util.version import (
    GHCR_IMAGE,
    _check_remote_version,
    _image_tag,
    _published_build,
    _read_base_version,
    check_for_update,
    get_version,
)


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
    with patch("backend.util.version.get_version", return_value="3.0.0.main50"):
        with patch(
            "backend.util.version._check_remote_version",
            return_value=("3.0.0.main55", 55, True),
        ):
            result = check_for_update(MagicMock())
    assert result["update_available"] is True
    assert result["local_version"] == "3.0.0.main50"
    assert result["remote_version"] == "3.0.0.main55"
    assert result["branch"] == "main"
    assert result["checked"] is True


def test_check_for_update_handles_network_failure():
    with patch("backend.util.version.get_version", return_value="3.0.0.develop12"):
        with patch(
            "backend.util.version._check_remote_version",
            return_value=(None, None, False),
        ):
            result = check_for_update(MagicMock())
    assert result["update_available"] is False
    assert result["checked"] is False
    assert result["branch"] == "develop"


# ----- update check compares against what is PUBLISHED, not commits on main ----


class _Resp:
    def __init__(self, payload=None, ok=True, status=200, text=None):
        self._payload, self.ok, self.status_code = payload, ok, status
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        return self._payload


def _host(url):
    """Parsed host — a substring test would match an attacker-controlled path."""
    return urlparse(url).netloc


def _ghcr(build_number="1550", **over):
    """URL -> response for a healthy GHCR read; `over` replaces one leg."""
    routes = {
        "token": _Resp({"token": "t"}),
        "manifests/full": _Resp({"manifests": [
            {"digest": "sha256:child", "platform": {"architecture": "amd64"}}]}),
        "manifests/latest": _Resp({"manifests": [
            {"digest": "sha256:child", "platform": {"architecture": "amd64"}}]}),
        "manifests/sha256:child": _Resp({"config": {"digest": "sha256:cfg"}}),
        "blobs/": _Resp({"config": {"Env": ["PATH=/usr/bin", f"BUILD_NUMBER={build_number}"]}}),
    }
    routes.update(over)

    def get(url, **kwargs):
        for key, resp in routes.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected URL {url}")

    return get


@pytest.mark.parametrize(
    "flavour,tag", [("full", "full"), ("lean", "latest"), (None, "latest")]
)
def test_published_build_reads_the_env_of_the_tag_its_flavour_tracks(
    monkeypatch, flavour, tag
):
    """A :full instance compared against :latest would read the wrong build, so
    the requested tag is asserted — not just the number that comes back."""
    if flavour is None:
        monkeypatch.delenv("CHUB_IMAGE_FLAVOR", raising=False)
    else:
        monkeypatch.setenv("CHUB_IMAGE_FLAVOR", flavour)
    seen, routed = [], _ghcr("1556")

    def get(url, **kwargs):
        seen.append(urlparse(url).path)
        return routed(url, **kwargs)

    monkeypatch.setattr("backend.util.version.requests.get", get)

    assert _published_build(MagicMock()) == 1556
    assert f"/v2/{GHCR_IMAGE}/manifests/{tag}" in seen


@pytest.mark.parametrize("leg", ["token", "manifests/latest", "blobs/"])
def test_published_build_is_none_when_the_registry_fails(leg, monkeypatch):
    """Unknown must never raise an update badge."""
    monkeypatch.setattr(
        "backend.util.version.requests.get", _ghcr(**{leg: _Resp(ok=False, status=503)})
    )
    assert _published_build(MagicMock()) is None


def test_image_tag_follows_the_flavour(monkeypatch):
    monkeypatch.setenv("CHUB_IMAGE_FLAVOR", "full")
    assert _image_tag() == "full"
    monkeypatch.setenv("CHUB_IMAGE_FLAVOR", "lean")
    assert _image_tag() == "latest"
    monkeypatch.delenv("CHUB_IMAGE_FLAVOR", raising=False)
    assert _image_tag() == "latest"


def test_commits_that_publish_no_image_do_not_raise_an_update(monkeypatch):
    """The bug this replaced: a docs/CI-only commit bumps the commit count on main
    but publishes nothing, so every user was told an update was ready that did not
    exist. The comparison must read the registry and never the commits API."""
    seen = []

    def get(url, **kwargs):
        seen.append(_host(url))
        if _host(url) == "raw.githubusercontent.com":
            return _Resp(text=json.dumps({".": "2.48.0"}))
        return _ghcr("1556")(url, **kwargs)

    monkeypatch.setattr("backend.util.version.requests.get", get)
    _remote, build, update = _check_remote_version(
        "2.48.0.main1556", "main", MagicMock()
    )

    assert build == 1556
    assert update is False, "running the newest published image is not an update"
    assert "api.github.com" not in seen, "must not count commits"


def test_a_newer_published_image_is_an_update(monkeypatch):
    def get(url, **kwargs):
        if _host(url) == "raw.githubusercontent.com":
            return _Resp(text=json.dumps({".": "2.48.0"}))
        return _ghcr("1560")(url, **kwargs)

    monkeypatch.setattr("backend.util.version.requests.get", get)
    _remote, build, update = _check_remote_version(
        "2.48.0.main1556", "main", MagicMock()
    )
    assert (build, update) == (1560, True)

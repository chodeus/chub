"""Shared pytest fixtures for CHUB test suite."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from backend.util.config import (
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    JduparrConfig,
    NohlConfig,
)


class StubLogger:
    """Minimal logger that satisfies the interface used across modules."""

    def __init__(self):
        self.messages = {"debug": [], "info": [], "warning": [], "error": []}

    def debug(self, *args, **kwargs):
        if args:
            self.messages["debug"].append(args[0])

    def info(self, *args, **kwargs):
        if args:
            self.messages["info"].append(args[0])

    def warning(self, *args, **kwargs):
        if args:
            self.messages["warning"].append(args[0])

    def error(self, *args, **kwargs):
        if args:
            self.messages["error"].append(args[0])

    def log_outro(self):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def stub_logger():
    return StubLogger()


@pytest.fixture
def empty_config():
    """A ChubConfig with no instances or paths configured."""
    return ChubConfig()


@pytest.fixture
def config_with_roots(tmp_path):
    """Build a config with concrete filesystem roots pinned under tmp_path."""
    posters_src = tmp_path / "posters_src"
    posters_dst = tmp_path / "posters_dst"
    nohl_src = tmp_path / "nohl_src"
    jdup_src = tmp_path / "jdup_src"
    for d in (posters_src, posters_dst, nohl_src, jdup_src):
        d.mkdir()

    config = ChubConfig()
    config.poster_renamerr.source_dirs = [str(posters_src)]
    config.poster_renamerr.destination_dir = str(posters_dst)
    config.nohl = NohlConfig(source_dirs=[str(nohl_src)])
    config.jduparr = JduparrConfig(source_dirs=[str(jdup_src)])
    return config, tmp_path


@pytest.fixture
def tightening_config(monkeypatch):
    """Factory: patch load_config to authorize `allowed` for the first N calls, then nothing."""

    def _install(allowed, authorized_calls=1):
        calls = []

        def _load():
            calls.append(1)
            config = ChubConfig()
            if len(calls) <= authorized_calls:
                config.poster_renamerr.source_dirs = [str(allowed)]
            return config

        monkeypatch.setattr("backend.util.config.load_config", _load)
        return calls

    return _install


@pytest.fixture
def instances_config():
    return InstancesConfig(
        radarr={
            "radarr_main": InstanceDetail(url="http://radarr:7878", api="abc"),
        },
        sonarr={
            "sonarr_main": InstanceDetail(url="http://sonarr:8989", api="def"),
        },
        plex={
            "plex_main": InstanceDetail(url="http://plex:32400", api="token"),
        },
    )

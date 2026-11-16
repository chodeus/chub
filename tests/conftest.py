"""Shared pytest fixtures for CHUB test suite."""

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Test files import this as tests.conftest: reuse this load rather than run it a second time.
sys.modules.setdefault("tests.conftest", sys.modules[__name__])
_REPO = Path(__file__).resolve().parents[1]
# Set before any backend import reads them, so CHUB's config, database and logs go to a temp folder.
_STATE_DIR = tempfile.mkdtemp(prefix="chub-tests-")
os.environ["CONFIG_DIR"] = _STATE_DIR
os.environ["LOG_DIR"] = os.path.join(_STATE_DIR, "logs")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util import paths  # noqa: E402
from backend.util.config import (  # noqa: E402
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    JduparrConfig,
    NohlConfig,
)

# Also moves the <repo>/config and <repo>/logs fallbacks and the legacy <repo>/config/chub.db.
paths._REPO_ROOT = Path(_STATE_DIR)


def _checkout_state() -> dict:
    """Each path under the checkout's config and log folders: a file's mtime, or -1 for a folder."""
    state = {}
    for folder in ("logs", "config", "tests/.cfgtmp"):
        root = _REPO / folder
        for path in (root, *root.rglob("*")) if root.exists() else ():
            try:
                st = path.lstat()
            except OSError:
                continue
            state[str(path.relative_to(_REPO))] = -1 if stat.S_ISDIR(st.st_mode) else st.st_mtime_ns
    return state


_BEFORE = _checkout_state()


def pytest_sessionfinish(session):
    """Remove the tests' state folder, and fail the run if the checkout's config or log folders changed."""
    shutil.rmtree(_STATE_DIR, ignore_errors=True)
    after = _checkout_state()
    stray = sorted(p for p in _BEFORE.keys() | after.keys() if _BEFORE.get(p) != after.get(p))
    if not stray:
        return
    message = "These checkout paths changed during the test run; tests write under tmp_path: " + ", ".join(stray)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_line(message, red=True)
    else:
        sys.stderr.write(message + "\n")
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


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


class _NoopConnector:
    """Connector double: every sync succeeds and changes nothing."""

    def __init__(self, db=None, logger=None, instance_map=None):
        self.instance_map = instance_map or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update_arr_database(self):
        return [
            SimpleNamespace(instance_name=name, success=True)
            for name in self.instance_map.get("arrs", [])
        ]

    def update_collections_database(self):
        return [
            SimpleNamespace(instance_name=name, success=True)
            for name in self.instance_map.get("plex", {})
        ]


@pytest.fixture
def noop_media_resync(monkeypatch):
    """resync_media succeeds without contacting any app."""
    monkeypatch.setattr("backend.util.connector.Connector", _NoopConnector)


@pytest.fixture
def umask_022():
    """Pin the umask, so a new file's mode (0o644) differs from a 0o600 source's."""
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)

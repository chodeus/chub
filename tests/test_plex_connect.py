"""Tests for backend.util.plex.connect_plex_with_retry — the shared
server-level connect-with-retry used by poster_cleanarr and plex_maintenance."""

import backend.util.plex as plex_mod
from backend.util.plex import connect_plex_with_retry


class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def test_connect_success(monkeypatch):
    class FakeServer:
        version = "1.2.3"

        def __init__(self, url, token, timeout=None):
            pass

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    server = connect_plex_with_retry("http://x", "tok", _Log(), instance_name="p")
    assert isinstance(server, FakeServer)


def test_connect_auth_failure_returns_none_without_retry(monkeypatch):
    calls = {"n": 0}

    class FakeServer:
        def __init__(self, *a, **k):
            calls["n"] += 1
            raise Exception("401 Unauthorized")

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    monkeypatch.setattr(plex_mod.time, "sleep", lambda s: None)
    assert connect_plex_with_retry("http://x", "tok", _Log(), max_retries=3) is None
    assert calls["n"] == 1  # auth failure is terminal — no retry


def test_connect_retries_then_succeeds(monkeypatch):
    state = {"n": 0}

    class FakeServer:
        version = "9"

        def __init__(self, *a, **k):
            state["n"] += 1
            if state["n"] < 3:
                raise Exception("connection refused")

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    monkeypatch.setattr(plex_mod.time, "sleep", lambda s: None)
    server = connect_plex_with_retry("http://x", "tok", _Log(), max_retries=5)
    assert server is not None
    assert state["n"] == 3


def test_connect_gives_up_after_max_retries(monkeypatch):
    class FakeServer:
        def __init__(self, *a, **k):
            raise Exception("connection refused")

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    monkeypatch.setattr(plex_mod.time, "sleep", lambda s: None)
    assert connect_plex_with_retry("http://x", "tok", _Log(), max_retries=2) is None

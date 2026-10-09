"""The unchanged-upload skip reads the Plex snapshot only after refreshing it."""

from types import SimpleNamespace

from backend.modules.poster_renamerr import PosterRenamerr


def _module(warnings):
    m = PosterRenamerr.__new__(PosterRenamerr)
    m.logger = SimpleNamespace(warning=warnings.append, debug=lambda *a, **k: None)
    m.full_config = SimpleNamespace()
    m.config = SimpleNamespace(
        plex_scope=[
            SimpleNamespace(instance="plex_main", library_names=["Films"], add_posters=True),
            SimpleNamespace(instance="plex_off", library_names=[], add_posters=False),
        ]
    )
    return m


def _db(events):
    return SimpleNamespace(
        plex=SimpleNamespace(get_by_instance=lambda name: events.append(("read", name)) or [])
    )


def test_refreshes_the_upload_instances_before_reading_them(monkeypatch):
    events, warnings = [], []
    monkeypatch.setattr(
        "backend.util.plex_refresh.refresh_plex_cache_if_stale",
        lambda db, cfg, logger, enabled: events.append(("refresh", enabled)),
    )

    _module(warnings)._build_upload_lib_indexes(_db(events))

    assert events == [("refresh", {"plex_main": ["Films"]}), ("read", "plex_main")]
    assert warnings == []


def test_a_failed_refresh_is_logged_and_the_check_still_runs(monkeypatch):
    events, warnings = [], []

    def boom(*a, **k):
        raise RuntimeError("plex down")

    monkeypatch.setattr("backend.util.plex_refresh.refresh_plex_cache_if_stale", boom)

    _module(warnings)._build_upload_lib_indexes(_db(events))

    assert events == [("read", "plex_main")]
    assert len(warnings) == 1

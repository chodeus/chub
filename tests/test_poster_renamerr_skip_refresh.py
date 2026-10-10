"""The unchanged-upload skip reads the Plex snapshot only after refreshing it."""

from types import SimpleNamespace

from backend.modules.poster_renamerr import PosterRenamerr


def _module(warnings):
    m = PosterRenamerr.__new__(PosterRenamerr)
    m.logger = SimpleNamespace(
        warning=lambda msg, **k: warnings.append(msg), debug=lambda *a, **k: None
    )
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


def test_scopes_on_one_instance_are_merged_for_the_refresh_and_the_uploader():
    from backend.util.upload_posters import PosterUploader, upload_enabled_instances

    scope = lambda inst, libs, on=True: SimpleNamespace(  # noqa: E731
        instance=inst, library_names=libs, add_posters=on
    )
    scopes = [
        scope("a", ["Films"]),
        scope("a", ["Films 4K", "Films"]),
        scope("b", ["TV"]),
        scope("b", []),
        scope("c", ["Kids"], on=False),
    ]
    uploader = PosterUploader.__new__(PosterUploader)
    uploader.config = SimpleNamespace(plex_scope=scopes)
    uploader.logger = SimpleNamespace(debug=lambda *a, **k: None)

    merged = upload_enabled_instances(scopes)
    used = uploader._get_enabled_instances()

    assert merged == {"a": ["Films", "Films 4K"], "b": []}
    assert used == merged


def test_the_skip_refresh_uses_the_merged_scopes(monkeypatch):
    events, warnings = [], []
    monkeypatch.setattr(
        "backend.util.plex_refresh.refresh_plex_cache_if_stale",
        lambda db, cfg, logger, enabled: events.append(("refresh", enabled)),
    )
    m = _module(warnings)
    m.config.plex_scope.append(
        SimpleNamespace(instance="plex_main", library_names=["Films 4K"], add_posters=True)
    )

    m._build_upload_lib_indexes(_db(events))

    assert events[0] == ("refresh", {"plex_main": ["Films", "Films 4K"]})


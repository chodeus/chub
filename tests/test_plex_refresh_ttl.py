"""Tests for refresh_plex_cache_if_stale's per-(instance, library) TTL guard.

The guard must reuse a fresh snapshot (the optimization) but still force a walk
when ANY required library is missing or stale — a per-instance MAX(updated_at)
would let one fresh library mask a never-walked sibling, which silently skipped
whole libraries for callers (labelarr) that read the snapshot with no live
per-item fallback.
"""

from types import SimpleNamespace
from unittest import mock

from backend.util import plex_refresh


def _logger():
    return SimpleNamespace(debug=lambda *a, **k: None)


class _FakePlex:
    """db.plex stub: ages keyed by (instance, library); None = never walked."""

    def __init__(self, ages):
        self.ages = ages

    def last_synced_age_seconds(self, instance_name=None, library_name=None):
        return self.ages.get((instance_name, library_name))


def _run(ages, enabled, ttl=300):
    db = SimpleNamespace(plex=_FakePlex(ages))
    full_config = SimpleNamespace(general=SimpleNamespace(plex_cache_ttl_seconds=ttl))
    with mock.patch("backend.util.connector.Connector") as Conn:
        walked = plex_refresh.refresh_plex_cache_if_stale(
            db, full_config, _logger(), enabled
        )
    return walked, Conn


def test_all_libraries_fresh_reuses_snapshot():
    walked, Conn = _run(
        {("Plex", "Movies"): 10.0, ("Plex", "TV Shows"): 20.0},
        {"Plex": ["Movies", "TV Shows"]},
    )
    assert walked is False
    Conn.assert_not_called()  # snapshot reused — optimization preserved


def test_one_library_never_walked_forces_refresh():
    # Movies fresh, TV Shows never walked (None). A per-instance MAX would see
    # Movies and wrongly skip; per-library must refresh.
    walked, Conn = _run(
        {("Plex", "Movies"): 10.0, ("Plex", "TV Shows"): None},
        {"Plex": ["Movies", "TV Shows"]},
    )
    assert walked is True
    Conn.return_value.update_plex_database.assert_called_once()


def test_one_library_stale_forces_refresh():
    walked, Conn = _run(
        {("Plex", "Movies"): 10.0, ("Plex", "TV Shows"): 9999.0},
        {"Plex": ["Movies", "TV Shows"]},
        ttl=300,
    )
    assert walked is True
    Conn.return_value.update_plex_database.assert_called_once()


def test_empty_library_list_falls_back_to_instance_scope():
    # No library list → instance-wide check (library_name=None key).
    walked, _ = _run({("Plex", None): 10.0}, {"Plex": []})
    assert walked is False


def test_empty_instance_set_is_noop():
    walked, Conn = _run({}, {})
    assert walked is False
    Conn.assert_not_called()

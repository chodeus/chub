"""Regression test for media_cache.delete + sync_for_instance cleanup.

The original delete() was gated on `item.get("renamed_file")` — a remnant
from when the (now-removed) pending_deletions ledger fanned out deletions
to disk. After the cleanarr rewrite ripped that ledger out, the guard
stayed and quietly turned delete() into a no-op for any row without a
renamed file. That left rows that the *arr no longer reported lingering
forever in media_cache. Combined with the has_content backfill migration
nulling out pre-schema rows, those stragglers slipped past the
`has_content is not None and not has_content` gate in unmatched_assets —
e.g. Heated Rivalry S2 stayed flagged as missing-poster after Sonarr had
stopped returning it.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.database import ChubDB  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    try:
        yield db
    finally:
        db.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            pass


def _sonarr_show_with_seasons(season_numbers, with_files=()):
    """Build a normalize_arr_media-shaped show with the requested seasons."""
    season_list = []
    for n in season_numbers:
        has_files = n in with_files
        season_list.append(
            {
                "season_number": n,
                "monitored": True,
                "season_pack": has_files,
                "season_has_episodes": 10 if has_files else 0,
                "episode_data": [],
            }
        )
    return {
        "title": "Heated Rivalry",
        "year": 2025,
        "media_id": 1,
        "arr_id": 1,
        "tmdb_id": None,
        "tvdb_id": 464461,
        "imdb_id": "tt35495073",
        "monitored": True,
        "status": "continuing",
        "root_folder": "/data/media/shows",
        "quality_profile": 1,
        "normalized_title": "heated rivalry",
        "alternate_titles": [],
        "normalized_alternate_titles": [],
        "folder": "Heated Rivalry (2025)",
        "has_content": any(n in with_files for n in season_numbers),
        "tags": [],
        "season_number": None,
        "seasons": season_list,
        "poster_url": None,
        "rating": None,
        "studio": None,
        "edition": None,
        "runtime": 45,
        "language": "en",
        "genre": None,
    }


def _fan_out_for_db(show):
    """Mirror connector._process_arr_media: show row + per-season rows."""
    rows = []
    show_row = dict(show)
    show_row["season_number"] = None
    rows.append(show_row)
    for season in show.get("seasons", []):
        season_row = dict(show)
        season_row["season_number"] = season["season_number"]
        season_row["has_content"] = (season.get("season_has_episodes") or 0) > 0
        season_row["monitored"] = season.get("monitored", True)
        rows.append(season_row)
    return rows


def test_sync_removes_seasons_no_longer_in_arr_response(db):
    """First sync stamps S1+S2; second sync drops S2; the S2 row must be
    physically deleted. Previously, the row lingered with stale data
    because delete() short-circuited on missing renamed_file."""
    # Initial state: Sonarr returns S1 (with files) and S2 (announced).
    show = _sonarr_show_with_seasons([1, 2], with_files=[1])
    db.media.sync_for_instance("sonarr", "Sonarr", "show", _fan_out_for_db(show))

    rows = db.media.execute_query(
        "SELECT season_number, has_content FROM media_cache WHERE title=? ORDER BY season_number",
        ("Heated Rivalry",),
        fetch_all=True,
    )
    season_to_has_content = {
        r["season_number"]: r["has_content"] for r in rows
    }
    assert 1 in season_to_has_content
    assert 2 in season_to_has_content
    assert season_to_has_content[1] == 1  # S1 has files
    assert season_to_has_content[2] == 0  # S2 no files

    # Now Sonarr drops S2 from its response (cancelled, unmonitored, or
    # the season collapsed back to "future"). sync_for_instance must
    # remove the stale row.
    show_without_s2 = _sonarr_show_with_seasons([1], with_files=[1])
    db.media.sync_for_instance(
        "sonarr", "Sonarr", "show", _fan_out_for_db(show_without_s2)
    )

    rows_after = db.media.execute_query(
        "SELECT season_number FROM media_cache WHERE title=?",
        ("Heated Rivalry",),
        fetch_all=True,
    )
    remaining = {r["season_number"] for r in rows_after}
    assert 2 not in remaining, (
        "S2 row should have been deleted when Sonarr stopped returning it,"
        " but it lingered — regression of the delete() renamed_file gate."
    )


def test_sync_updates_has_content_when_season_re_appears_with_files(db):
    """Sanity check: an existing row's has_content is overwritten by a
    re-sync that finds files on disk. Belt-and-braces alongside the
    delete fix — the upsert path was always supposed to do this."""
    show = _sonarr_show_with_seasons([1, 2], with_files=[1])
    db.media.sync_for_instance("sonarr", "Sonarr", "show", _fan_out_for_db(show))

    # User finally downloads S2 — Sonarr now reports episodeFileCount > 0.
    show_with_s2_files = _sonarr_show_with_seasons([1, 2], with_files=[1, 2])
    db.media.sync_for_instance(
        "sonarr", "Sonarr", "show", _fan_out_for_db(show_with_s2_files)
    )

    row = db.media.execute_query(
        "SELECT has_content FROM media_cache WHERE title=? AND season_number=?",
        ("Heated Rivalry", 2),
        fetch_one=True,
    )
    assert row is not None
    assert row["has_content"] == 1

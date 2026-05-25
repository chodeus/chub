"""Tests for backend/modules/poster_renamerr.py — asset classifier + walk behavior.

Targets the behavior introduced in commit 57cd537 ("Improve poster asset
matching and cache handling"), specifically:

* ``_classify_asset_record`` — pure decision: movie / show / collection
* ``_get_assets_files`` — strips season tokens from titles, sorts walk
  output deterministically, and post-classifies records using sibling
  show_keys so e.g. a "Show (2020)" main poster sitting next to "Show
  (2020) - Season 01.jpg" gets classified as ``show``, not ``movie``.
"""

import os
from types import SimpleNamespace


from backend.modules.poster_renamerr import PosterRenamerr


def make_module():
    m = object.__new__(PosterRenamerr)
    m.logger = SimpleNamespace(
        debug=lambda *a, **kw: None,
        info=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    m._cancel_event = None
    return m


# --- _classify_asset_record ---


def test_classify_season_poster_is_show():
    m = make_module()
    record = {"season_number": 1, "year": 2020, "normalized_title": "show"}
    assert m._classify_asset_record(record, set()) == "show"


def test_classify_record_with_tvdb_id_is_show():
    m = make_module()
    record = {
        "season_number": None,
        "year": 2020,
        "tvdb_id": 1234,
        "normalized_title": "show",
    }
    assert m._classify_asset_record(record, set()) == "show"


def test_classify_main_poster_with_show_sibling_promotes_to_show():
    """A main "Show (2020).jpg" sitting alongside "Show (2020) - Season 01.jpg"
    should classify as `show`, not `movie`."""
    m = make_module()
    record = {
        "season_number": None,
        "year": 2020,
        "normalized_title": "show",
    }
    show_keys = {("show", 2020)}
    assert m._classify_asset_record(record, show_keys) == "show"


def test_classify_main_poster_no_sibling_is_movie():
    m = make_module()
    record = {
        "season_number": None,
        "year": 2020,
        "normalized_title": "inception",
    }
    assert m._classify_asset_record(record, set()) == "movie"


def test_classify_record_without_year_is_collection():
    m = make_module()
    record = {
        "season_number": None,
        "year": None,
        "normalized_title": "marvelcinematic",
    }
    assert m._classify_asset_record(record, set()) == "collection"


def test_classify_year_zero_treated_as_present_year():
    """A year of 0 is not None — it should not be classified as collection."""
    m = make_module()
    record = {
        "season_number": None,
        "year": 0,
        "normalized_title": "weird",
    }
    # 0 is not None, so falls through to "movie" branch
    assert m._classify_asset_record(record, set()) == "movie"


def test_classify_show_key_match_requires_year():
    """If year is None, the show_keys lookup is bypassed (record is collection)."""
    m = make_module()
    record = {
        "season_number": None,
        "year": None,
        "normalized_title": "show",
    }
    show_keys = {("show", None)}
    assert m._classify_asset_record(record, show_keys) == "collection"


# --- _get_assets_files ---


def _make_asset_tree(root, files):
    """Helper: drop a set of fake poster files into the given directory."""
    for relpath in files:
        full = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(b"x")


def test_get_assets_files_strips_season_tokens_from_title(tmp_path):
    """Filenames like 'Show (2020) - Season 01.jpg' should yield a title of
    'Show' once season tokens are stripped."""
    m = make_module()
    _make_asset_tree(
        str(tmp_path),
        ["Show (2020) - Season 01.jpg"],
    )
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    rec = records[0]
    assert rec["title"] == "Show"
    assert rec["season_number"] == 1
    assert rec["year"] == 2020


def test_get_assets_files_classifies_show_with_main_and_season(tmp_path):
    """Main poster + season poster: both should classify as `show`."""
    m = make_module()
    _make_asset_tree(
        str(tmp_path),
        [
            "Show (2020).jpg",
            "Show (2020) - Season 01.jpg",
        ],
    )
    records = m._get_assets_files(str(tmp_path))
    by_season = {r["season_number"]: r for r in records}
    # Main entry — season_number is None
    assert by_season[None]["asset_type"] == "show"
    assert by_season[1]["asset_type"] == "show"


def test_get_assets_files_classifies_lone_movie(tmp_path):
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Inception (2010).jpg"])
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    assert records[0]["asset_type"] == "movie"


def test_get_assets_files_classifies_collection_when_no_year(tmp_path):
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Marvel Cinematic Universe Collection.jpg"])
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    assert records[0]["asset_type"] == "collection"


def test_get_assets_files_walk_is_deterministically_sorted(tmp_path):
    """Files within a folder should come back in case-insensitive sorted order."""
    m = make_module()
    _make_asset_tree(
        str(tmp_path),
        ["beta (2020).jpg", "Alpha (2020).jpg", "gamma (2020).jpg"],
    )
    records = m._get_assets_files(str(tmp_path))
    titles = [r["title"] for r in records]
    assert titles == ["Alpha", "beta", "gamma"]


def test_get_assets_files_skips_non_poster_extensions(tmp_path):
    m = make_module()
    _make_asset_tree(
        str(tmp_path),
        ["Movie (2020).jpg", "Movie (2020).txt", "Movie (2020).nfo"],
    )
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    assert records[0]["file"].endswith(".jpg")


def test_get_assets_files_accepts_webp(tmp_path):
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Movie (2020).webp"])
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1


def test_get_assets_files_strips_bracket_id_tokens(tmp_path):
    """The widened id_content_regex strips [tmdb-123] from titles."""
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Movie [tmdb-12345] (2020).jpg"])
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    assert "tmdb" not in records[0]["title"].lower()
    assert records[0]["tmdb_id"] == 12345


def test_get_assets_files_specials_yield_season_zero(tmp_path):
    """Files matching 'Specials' should yield season_number=0."""
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Show (2020) - Specials.jpg"])
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    assert records[0]["season_number"] == 0


def test_get_assets_files_singular_special_in_movie_title(tmp_path):
    """Singular 'Special' in a movie title must not be treated as a season marker.

    Regression: 'X-Men First Class 35mm Special (2012)' was being parsed as
    a season-0 show with title 'X-Men First Class 35mm', which broke both
    ID-based and title-based matching against the Radarr row.
    """
    m = make_module()
    _make_asset_tree(
        str(tmp_path),
        ["X-Men First Class 35mm Special (2012) {tmdb-691677} {imdb-tt1948218}.jpg"],
    )
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    record = records[0]
    assert record["title"] == "X-Men First Class 35mm Special"
    assert record["season_number"] is None
    assert record["asset_type"] == "movie"
    assert record["tmdb_id"] == 691677
    assert record["imdb_id"] == "tt1948218"


# --- source_dirs bottom-wins contract ---
#
# These tests defend the contract documented in
# backend/util/database/poster_cache.py: when two source_dirs contain a
# poster for the same media item, the entry from the **bottom** of
# poster_renamerr.source_dirs wins. Three things must hold for that to
# work: (1) the priority stamp on each asset, (2) the ORDER BY in the
# match-phase queries, (3) the upsert preserving the priority column.
#
# If a future refactor removes any of those, these tests fail loudly.
# See git history around PR #143 and commit 3be5dfe for the original
# regression these are guarding against.


def test_get_assets_files_stamps_priority(tmp_path):
    """`_get_assets_files` must propagate the `priority` kwarg onto every
    record so the merge phase can stamp source_dir position."""
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Movie (2020).jpg", "Other (2021).jpg"])
    records = m._get_assets_files(str(tmp_path), priority=7)
    assert len(records) == 2
    assert all(r["priority"] == 7 for r in records)


def test_get_assets_files_defaults_priority_to_zero(tmp_path):
    """Callers that don't pass priority (legacy paths, ad-hoc tests) get 0."""
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Movie (2020).jpg"])
    records = m._get_assets_files(str(tmp_path))
    assert records[0]["priority"] == 0


def _make_poster_record(file_path: str, priority: int) -> dict:
    """Two records with the same key (title/year/ids) but different files
    and priorities — what 'two contributors with a poster for the same
    movie' looks like in the cache."""
    return {
        "asset_type": "movie",
        "title": "Inception",
        "normalized_title": "inception",
        "year": 2010,
        "tmdb_id": 27205,
        "tvdb_id": None,
        "imdb_id": "tt1375666",
        "season_number": None,
        "folder": "Inception (2010)",
        "file": file_path,
        "style": None,
        "priority": priority,
    }


def test_source_dirs_bottom_wins(tmp_path):
    """The load-bearing guardrail.

    Two source_dirs each contain a poster for the same movie. The bottom
    source_dir (priority=1) must win when the match-phase queries the
    cache. If this test ever fails, the bottom-wins contract has been
    broken — likely by an ORDER BY drop in poster_cache.py, by the
    priority column getting nuked, or by merge_assets no longer stamping
    each asset's priority. See the CONTRACT block in
    backend/util/database/poster_cache.py before "fixing" the test.
    """
    import os as _os
    import sys as _sys
    import tempfile

    _sys.path.insert(
        0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
    )

    from backend.util.database import ChubDB

    class _StubLogger:
        def __getattr__(self, _name):
            return lambda *a, **kw: None

        def get_adapter(self, *a, **kw):
            return self

    fd, db_path = tempfile.mkstemp(suffix=".db")
    _os.close(fd)
    db = ChubDB(logger=_StubLogger(), db_path=db_path, quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    try:
        top_file = str(tmp_path / "top_source" / "Inception (2010).jpg")
        bottom_file = str(tmp_path / "bottom_source" / "Inception (2010).jpg")

        # Insert top first (mirrors merge_assets iterating source_dirs
        # top-to-bottom). The rowid ordering would favor the top row if
        # ORDER BY priority were missing — so this insertion order is
        # the adversarial case the test guards against.
        db.poster.upsert(_make_poster_record(top_file, priority=0))
        db.poster.upsert(_make_poster_record(bottom_file, priority=1))

        # 1. ID-based match: get_by_id must return the bottom row.
        by_imdb = db.poster.get_by_id("imdb_id", "tt1375666", asset_type="movie")
        assert by_imdb is not None
        assert by_imdb["file"] == bottom_file, (
            "ID-based match returned the wrong row — bottom-wins contract broken. "
            "Check ORDER BY priority DESC in poster_cache.get_by_id."
        )

        # 2. Title-prefix candidates: bottom row must come first.
        candidates = db.poster.get_candidates_by_prefix("Inception", asset_type="movie")
        assert len(candidates) >= 2
        assert candidates[0]["file"] == bottom_file, (
            "Title-prefix candidates returned in wrong order — bottom-wins "
            "contract broken. Check ORDER BY priority DESC in "
            "poster_cache.get_candidates_by_prefix."
        )

        # 3. Normalized-title match: must also return the bottom row.
        by_title = db.poster.get_by_normalized_title(
            "inception", year=2010, asset_type="movie"
        )
        assert by_title is not None
        assert by_title["file"] == bottom_file, (
            "Normalized-title match returned the wrong row — bottom-wins "
            "contract broken. Check ORDER BY priority DESC in "
            "poster_cache.get_by_normalized_title."
        )
    finally:
        db.__exit__(None, None, None)
        try:
            _os.unlink(db_path)
        except OSError:
            pass


# --- orphan-pass scan scope contract ---
#
# Defends the contract documented on PosterRenamerr._orphan_pass_scan_roots:
# the post-rename orphan-asset pass walks ONLY destination_dir. source_dirs
# are deliberately out of scope. If a future refactor unions source_dirs
# back into the scan set, this test fails — fix the refactor, not the test.


def _module_with_config(destination_dir, source_dirs):
    m = make_module()
    m.config = SimpleNamespace(
        destination_dir=destination_dir,
        source_dirs=list(source_dirs),
    )
    return m


def test_orphan_pass_scan_roots_returns_destination_only():
    m = _module_with_config(
        destination_dir="/kometa/assets",
        source_dirs=["/kometa/posters/CL2K/Dweagle79"],
    )
    assert m._orphan_pass_scan_roots() == ["/kometa/assets"]


def test_orphan_pass_scan_roots_excludes_source_dirs():
    """The load-bearing scope guardrail.

    Even with multiple source_dirs configured (and what looks like a
    convincing "asset directory" structure), the orphan pass must scan
    destination only. If this test fails, the post-rename orphan pass
    is reaching into user-owned or gdrive-backed territory.
    """
    m = _module_with_config(
        destination_dir="/kometa/assets",
        source_dirs=[
            "/kometa/posters/CL2K/Dweagle79",
            "/kometa/posters/CL2K/Iamspartacus",
            "/kometa/posters/_personal",
        ],
    )
    roots = m._orphan_pass_scan_roots()
    assert "/kometa/posters/CL2K/Dweagle79" not in roots, (
        "Orphan scan must not include gdrive-synced source dirs — "
        "they'd churn delete/restore on every cycle."
    )
    assert "/kometa/posters/_personal" not in roots, (
        "Orphan scan must not include personal source dirs — "
        "CHUB has no authority to delete user-owned posters."
    )
    assert roots == ["/kometa/assets"]


def test_orphan_pass_scan_roots_empty_when_no_destination():
    """Without a destination_dir the orphan pass has nothing to scan.

    Returning an empty list (rather than [None] or [""]) keeps the
    downstream walker from doing anything surprising on bad config.
    """
    m = _module_with_config(destination_dir="", source_dirs=["/some/source"])
    assert m._orphan_pass_scan_roots() == []

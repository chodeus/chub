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

import pytest


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


def test_classify_year_less_record_with_imdb_id_is_movie():
    """A TMDB collection never has an IMDb id, so "Leo 2 {tmdb-…} {imdb-tt…}.jpg"
    is a movie whose filename omitted the year — not a collection."""
    m = make_module()
    record = {
        "season_number": None,
        "year": None,
        "imdb_id": "tt31066554",
        "normalized_title": "leo2",
    }
    assert m._classify_asset_record(record, set()) == "movie"


def test_classify_year_less_collection_with_tmdb_id_stays_collection():
    """Real collection posters DO carry {tmdb-…}, so only IMDb may veto."""
    m = make_module()
    record = {
        "season_number": None,
        "year": None,
        "tmdb_id": 1511685,
        "normalized_title": "dedepyaardecollection",
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


def test_get_assets_files_folder_based_bare_season_still_detected(tmp_path):
    """A folder-based layout where the season file is bare 'Season01.jpg' (no
    ' - ' delimiter) must still yield a season_number — the start-of-name
    anchor preserves this while a bare 'Season N' inside a movie title does
    not match."""
    m = make_module()
    _make_asset_tree(str(tmp_path), ["Show (2020)/Season01.jpg"])
    records = m._get_assets_files(str(tmp_path))
    assert len(records) == 1
    assert records[0]["season_number"] == 1


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


def test_get_assets_files_bare_season_in_movie_title_is_movie(tmp_path):
    """A bare "Season <n>" inside a movie title (no " - "/"_" delimiter) must
    NOT be treated as a TV season marker.

    Regression: 'Open Season 2 (2008)' / 'Open Season 3 (2010)' were parsed as
    season-2/3 shows with title 'Open' — so the file vanished from asset search
    (normalized_title became 'open') and never matched the Radarr movie row.
    A real season poster always delimits the tag ('Show (2020) - Season 1'),
    so only the delimited form should be stripped.
    """
    m = make_module()
    _make_asset_tree(
        str(tmp_path),
        [
            "Open Season 2 (2008) {tmdb-13690} {imdb-tt1107365}.jpg",
            "Open Season 3 (2010) {tmdb-51170} {imdb-tt1646926}.jpg",
        ],
    )
    records = m._get_assets_files(str(tmp_path))
    by_title = {r["title"]: r for r in records}

    rec2 = by_title["Open Season 2"]
    assert rec2["season_number"] is None
    assert rec2["asset_type"] == "movie"
    assert rec2["normalized_title"] == "openseason2"
    assert rec2["tmdb_id"] == 13690
    assert rec2["imdb_id"] == "tt1107365"

    rec3 = by_title["Open Season 3"]
    assert rec3["season_number"] is None
    assert rec3["asset_type"] == "movie"
    assert rec3["normalized_title"] == "openseason3"
    assert rec3["tmdb_id"] == 51170


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


# --- GDrive-as-source: drives are matchable by default, opt out via search_only ---


def _gdrive(location, search_only=False, name="CL2K Solen"):
    return SimpleNamespace(location=location, search_only=search_only, name=name)


def _module_with_gdrive(source_dirs, gdrive, asset_dirs=()):
    m = make_module()
    m.config = SimpleNamespace(source_dirs=list(source_dirs))
    m.full_config = SimpleNamespace(
        sync_gdrive=SimpleNamespace(gdrive_list=list(gdrive)),
        asset_renamerr=SimpleNamespace(source_dirs=list(asset_dirs)),
    )
    return m


def test_gdrive_match_locations_excludes_search_only():
    m = _module_with_gdrive(
        source_dirs=[],
        gdrive=[_gdrive("/gdrive/CL2K"), _gdrive("/gdrive/Extras", search_only=True)],
    )
    assert m._gdrive_match_locations() == ["/gdrive/CL2K"]


def test_scan_source_dirs_unions_gdrive_and_dedupes():
    m = _module_with_gdrive(
        source_dirs=["/local/posters", "/gdrive/CL2K"],
        gdrive=[
            _gdrive("/gdrive/CL2K"),  # already a source_dir → not duplicated
            _gdrive("/gdrive/MM2K"),  # auto-included, appended after locals
            _gdrive("/gdrive/Extras", search_only=True),  # browse-only → excluded
        ],
    )
    # source_dirs keep their order/position; the new matchable drive appends.
    assert m._scan_source_dirs() == ["/local/posters", "/gdrive/CL2K", "/gdrive/MM2K"]


def test_matchable_source_dirs_includes_gdrive_and_assets():
    m = _module_with_gdrive(
        source_dirs=["/local/posters"],
        gdrive=[_gdrive("/gdrive/CL2K"), _gdrive("/gdrive/Extras", search_only=True)],
        asset_dirs=["/assets"],
    )
    matchable = m._matchable_source_dirs()
    assert "/local/posters" in matchable
    assert "/gdrive/CL2K" in matchable
    assert "/assets" in matchable
    # A browse-only drive is never matchable.
    assert "/gdrive/Extras" not in matchable


def test_orphan_pass_scan_roots_empty_when_no_destination():
    """Without a destination_dir the orphan pass has nothing to scan.

    Returning an empty list (rather than [None] or [""]) keeps the
    downstream walker from doing anything surprising on bad config.
    """
    m = _module_with_config(destination_dir="", source_dirs=["/some/source"])
    assert m._orphan_pass_scan_roots() == []


# --- match transparency: conflicts, status, pure helpers ---


def test_candidate_identity_prefers_tmdb_then_title():
    assert PosterRenamerr._candidate_identity({"tmdb_id": 5}) == ("tmdb", "5")
    assert PosterRenamerr._candidate_identity({"imdb_id": "TT9"}) == ("imdb", "tt9")
    assert PosterRenamerr._candidate_identity(
        {"normalized_title": "foo", "year": 2010}
    ) == ("title", "foo", 2010)


def test_append_rename_history_caps_and_appends():
    import json as _json

    out = PosterRenamerr._append_rename_history(None, "/src/Old.jpg", "/dst/new.jpg")
    parsed = _json.loads(out)
    assert parsed[-1]["old"] == "Old.jpg"
    assert parsed[-1]["new"] == "new.jpg"
    assert "at" in parsed[-1]
    # cap at 20
    big = _json.dumps([{"old": "a", "new": "b", "at": "t"}] * 25)
    capped = _json.loads(PosterRenamerr._append_rename_history(big, "x", "y"))
    assert len(capped) == 20


def _open_db(tmp_path, logger):
    from backend.util.database import ChubDB

    db = ChubDB(logger=logger, db_path=str(tmp_path / "match.db"), quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    return db


def test_match_item_clean_single_match_is_matched(tmp_path):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,file,priority) "
            "VALUES ('movie','Inception','inception',2010,27205,'/a.jpg',0)"
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,tmdb_id,instance_name) "
            "VALUES ('mk','movie','Inception','inception','2010',27205,'radarr')"
        )
        media = dict(
            db.media.execute_query(
                "SELECT * FROM media_cache WHERE identity_key='mk'", fetch_one=True
            )
        )
        result = m.match_item(media, db)
        assert result["matched"] is True
        updated = db.media.get_by_id(media["id"])
        assert updated["match_status"] == "matched"
        assert updated["match_confidence"] >= 0.95  # ID match
        assert updated["conflict_ids"] == "[]"
    finally:
        db.__exit__(None, None, None)


def test_match_item_conflicting_candidates_flagged_review(tmp_path):
    import json as _json

    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        # Two posters, same title/year, different tmdb ids -> ambiguous. Media
        # has no id so matching falls to the title path and finds both.
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,file,priority) "
            "VALUES ('movie','Ambiguous','ambiguous',2010,111,'/a.jpg',0)"
        )
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,file,priority) "
            "VALUES ('movie','Ambiguous','ambiguous',2010,222,'/b.jpg',1)"
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,instance_name) "
            "VALUES ('mk','movie','Ambiguous','ambiguous','2010','radarr')"
        )
        media = dict(
            db.media.execute_query(
                "SELECT * FROM media_cache WHERE identity_key='mk'", fetch_one=True
            )
        )
        result = m.match_item(media, db)
        assert result["matched"] is True  # priority-winner still applied
        updated = db.media.get_by_id(media["id"])
        assert updated["match_status"] == "needs_review"
        assert len(_json.loads(updated["conflict_ids"])) == 2
    finally:
        db.__exit__(None, None, None)


def test_match_item_stamps_matched_at_and_recently_matched(tmp_path):
    """A new match stamps matched_at + matched_poster_file and surfaces in
    get_recently_matched; re-confirming the same match keeps the original
    timestamp (so the reel reflects genuine recency, not scan order)."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,file,priority) "
            "VALUES ('movie','Inception','inception',2010,27205,'/a.jpg',0)"
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,tmdb_id,instance_name) "
            "VALUES ('mk','movie','Inception','inception','2010',27205,'radarr')"
        )

        def media_row():
            return dict(
                db.media.execute_query(
                    "SELECT * FROM media_cache WHERE identity_key='mk'", fetch_one=True
                )
            )

        # First match: stamps provenance.
        m.match_item(media_row(), db)
        row1 = media_row()
        assert row1["matched_poster_file"] == "/a.jpg"
        assert row1["matched_at"] is not None
        first_ts = row1["matched_at"]

        recent = db.media.get_recently_matched(50)
        assert [r["title"] for r in recent] == ["Inception"]

        # Re-confirm the same match: timestamp must NOT change.
        m.match_item(media_row(), db)
        assert media_row()["matched_at"] == first_ts
    finally:
        db.__exit__(None, None, None)


def test_match_item_no_id_article_prefixed_season_poster(tmp_path):
    """A season poster with NO id tags whose title starts with an article
    ('The Lovers - Season 1') must match its Sonarr season row via the title
    prefix path. Regression: get_prefix() stripped 'The' -> 'lov', which never
    matched the stored normalized_title 'thelovers', so these silently failed.
    """
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        # No-id show/season poster.
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,season_number,file,priority) "
            "VALUES ('show','The Lovers','thelovers',2023,1,'/lovers_s1.jpg',0)"
        )
        # Sonarr season row: has a tvdb id (the poster does not).
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,tvdb_id,season_number,instance_name) "
            "VALUES ('mk','show','The Lovers','thelovers','2023',421837,1,'sonarr')"
        )
        media = dict(
            db.media.execute_query(
                "SELECT * FROM media_cache WHERE identity_key='mk'", fetch_one=True
            )
        )
        result = m.match_item(media, db)
        assert result["matched"] is True
        assert result["match"]["file"] == "/lovers_s1.jpg"
    finally:
        db.__exit__(None, None, None)


# --- Fix A: conflict detection defers to priority -----------------------------


def test_no_conflict_same_title_id_presence():
    """A collection with one id-bearing poster and one id-less poster of the
    SAME title is not a conflict — priority picks one silently (no review)."""
    cands = [
        {"normalized_title": "phineasandferbcollection", "tmdb_id": None},
        {"normalized_title": "phineasandferbcollection", "tmdb_id": 12345},
    ]
    assert PosterRenamerr._has_identity_conflict(cands) is False


def test_conflict_when_titles_differ():
    cands = [
        {"normalized_title": "goodburgercollection"},
        {"normalized_title": "goonburgercollection"},
    ]
    assert PosterRenamerr._has_identity_conflict(cands) is True


def test_conflict_when_same_title_different_tmdb_ids():
    cands = [
        {"normalized_title": "x", "tmdb_id": 1},
        {"normalized_title": "x", "tmdb_id": 2},
    ]
    assert PosterRenamerr._has_identity_conflict(cands) is True


def test_single_candidate_never_conflicts():
    assert PosterRenamerr._has_identity_conflict([{"normalized_title": "x"}]) is False


# --- Fix B: user_confirmed lock survives re-scans -----------------------------


def test_user_confirmed_match_is_preserved():
    """A locked (manually applied) row must skip re-matching entirely so a
    scheduled re-scan can never revert it."""
    m = make_module()
    media = {
        "user_confirmed": 1,
        "matched": 1,
        "title": "Phineas and Ferb Collection",
        "year": None,
        "asset_type": "collection",
    }
    # db is never touched on the locked path, so None is fine.
    result = m.match_item(media, db=None, is_collection=True)
    assert result["matched"] is True
    assert "user_confirmed" in result["reasons"][0]


# --- Fix C: collection rename names by title when folder is empty -------------


def test_rename_file_collection_names_by_title(tmp_path):
    """Plex collections have no on-disk folder; rename_file must name the asset
    by the collection title instead of emitting a nameless '.jpg'."""
    src = tmp_path / "src.jpg"
    src.write_bytes(b"img")
    m = make_module()
    m.config = SimpleNamespace(
        destination_dir=str(tmp_path),
        asset_folders=False,
        dry_run=False,
        action_type="copy",
        run_border_replacerr=False,
        print_only_renames=False,
    )

    class _Iface:
        def update(self, **kwargs):
            pass

    db = SimpleNamespace(collection=_Iface(), media=_Iface())
    item = {
        "asset_type": "collection",
        "title": "Phineas and Ferb Collection",
        "folder": "",
        "original_file": str(src),
        "id": 1,
        "year": None,
    }
    m.rename_file(item, db)
    expected = tmp_path / "Phineas and Ferb Collection.jpg"
    assert expected.exists()
    assert item["renamed_file"].endswith("Phineas and Ferb Collection.jpg")


def test_match_item_skips_unchanged_write(tmp_path):
    """Steady-state skip (#6): a second match_item on byte-identical state
    issues NO row UPDATE and NO provenance UPDATE, but a real change forces both
    writes again. Provably safe — only a no-op write is skipped."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,file,priority) "
            "VALUES ('movie','Inception','inception',2010,27205,'/a.jpg',0)"
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,tmdb_id,instance_name) "
            "VALUES ('mk','movie','Inception','inception','2010',27205,'radarr')"
        )

        def media_row():
            return dict(
                db.media.execute_query(
                    "SELECT * FROM media_cache WHERE identity_key='mk'", fetch_one=True
                )
            )

        # Wrap update / set_match_provenance to count actual writes.
        counts = {"update": 0, "prov": 0}
        real_update = db.media.update
        real_prov = db.media.set_match_provenance

        def counting_update(*a, **k):
            counts["update"] += 1
            return real_update(*a, **k)

        def counting_prov(*a, **k):
            counts["prov"] += 1
            return real_prov(*a, **k)

        db.media.update = counting_update
        db.media.set_match_provenance = counting_prov

        # First run populates the row -> both writes happen.
        m.match_item(media_row(), db)
        assert counts == {"update": 1, "prov": 1}

        # Second run, identical state -> both writes skipped.
        m.match_item(media_row(), db)
        assert counts["update"] == 1, "unchanged match must skip the row UPDATE"
        assert counts["prov"] == 1, "unchanged match must skip the provenance UPDATE"

        # Real change: remove the matching poster so the row now UNmatches.
        db.poster.execute_query("DELETE FROM poster_cache")
        m.match_item(media_row(), db)
        assert counts["update"] == 2, "a real change must write the row again"
        assert counts["prov"] == 2, "clearing the match must write provenance"
        assert media_row()["matched"] == 0
    finally:
        db.__exit__(None, None, None)


# --- build_asset_record: music classification (Phase 4 sourcing) ---


def test_build_asset_record_music_folder_artist():
    from backend.modules.poster_renamerr import build_asset_record

    r = build_asset_record("artist.jpg", "/music/REZZ", music_root="/music")
    assert r["music_kind"] == "artist"
    assert r["title"] == "REZZ"
    assert r["parent_title"] is None


def test_build_asset_record_music_folder_album():
    from backend.modules.poster_renamerr import build_asset_record

    r = build_asset_record(
        "cover.jpg", "/music/REZZ/Mass Manipulation", music_root="/music"
    )
    assert r["music_kind"] == "album"
    assert r["title"] == "Mass Manipulation"
    assert r["parent_title"] == "REZZ"


def test_build_asset_record_music_flat_album():
    from backend.modules.poster_renamerr import build_asset_record

    r = build_asset_record(
        "Boards of Canada - Geogaddi.jpg", "/music", music_root="/music"
    )
    assert r["music_kind"] == "album"
    assert r["title"] == "Geogaddi"
    assert r["parent_title"] == "Boards of Canada"


def test_build_asset_record_mbid_tag_in_normal_dir():
    """An {mbid-} tag marks a file as music even outside a music source dir."""
    from backend.modules.poster_renamerr import build_asset_record

    r = build_asset_record(
        "REZZ {mbid-12345678-1234-1234-1234-123456789abc}.jpg", "/posters"
    )
    assert r["music_kind"] == "artist"
    assert r["title"] == "REZZ"
    assert r["musicbrainz_id"] == "12345678-1234-1234-1234-123456789abc"


def test_build_asset_record_movie_unaffected():
    """Non-music files keep the movie/show path (no music_kind)."""
    from backend.modules.poster_renamerr import build_asset_record

    r = build_asset_record("Inception (2010) {tmdb-27205}.jpg", "/posters")
    assert r.get("music_kind") is None
    assert r["tmdb_id"] == 27205


def test_classify_asset_record_honors_music_kind():
    m = make_module()
    assert m._classify_asset_record({"music_kind": "album"}, set()) == "album"
    assert m._classify_asset_record({"music_kind": "artist"}, set()) == "artist"


# --- _staged_dest / _needs_staging (media-folder rename drift) ---


def _staging_module(destination_dir="/kometa/assets", asset_folders=True):
    m = make_module()
    m.config = SimpleNamespace(
        destination_dir=destination_dir,
        asset_folders=asset_folders,
        dry_run=False,
        run_border_replacerr=False,
    )
    return m


def test_staged_dest_uses_current_folder():
    m = _staging_module()
    item = {
        "asset_type": "show",
        "folder": "Anthony Bourdain Parts Unknown (2013) {tvdb-264108}",
        "original_file": "/src/Anthony Bourdain Parts Unknown.jpg",
        "season_number": None,
    }
    assert m._staged_dest(item) == (
        "/kometa/assets/Anthony Bourdain Parts Unknown (2013) {tvdb-264108}/poster.jpg"
    )


def test_needs_staging_when_folder_renamed(tmp_path):
    """A matched asset staged under the OLD folder name (file still on disk)
    must be re-queued once the media folder is renamed — not skipped just
    because the stale file exists. This is the Bourdain/Dune-class bug."""
    m = _staging_module(destination_dir=str(tmp_path))
    old_dir = tmp_path / "Dune - Prophecy (2024) {tvdb-367118}"
    old_dir.mkdir()
    staged = old_dir / "poster.jpg"
    staged.write_bytes(b"x")
    row = {
        "asset_type": "show",
        "matched": 1,
        "folder": "Dune Prophecy (2024) {tvdb-367118}",  # corrected media folder
        "original_file": "/src/Dune Prophecy.jpg",
        "season_number": None,
        "renamed_file": str(staged),  # still points at the old hyphen folder
    }
    assert m._needs_staging(row) is True


def test_needs_staging_false_when_path_current(tmp_path):
    m = _staging_module(destination_dir=str(tmp_path))
    folder = "Dune Prophecy (2024) {tvdb-367118}"
    d = tmp_path / folder
    d.mkdir()
    staged = d / "poster.jpg"
    staged.write_bytes(b"x")
    row = {
        "asset_type": "show",
        "matched": 1,
        "folder": folder,
        "original_file": "/src/Dune Prophecy.jpg",
        "season_number": None,
        "renamed_file": str(staged),
    }
    assert m._needs_staging(row) is False


def test_needs_staging_when_nothing_staged():
    m = _staging_module()
    row = {
        "asset_type": "movie",
        "matched": 1,
        "folder": "Movie (2020)",
        "original_file": "/src/Movie.jpg",
        "season_number": None,
        "renamed_file": None,
    }
    assert m._needs_staging(row) is True


def test_remove_superseded_drops_old_folder(tmp_path):
    """Re-staging after a folder rename removes the stale file and its now-empty
    old folder — Kometa ignores it and the orphan pass spares its id, so it
    would otherwise linger forever."""
    m = _staging_module(destination_dir=str(tmp_path))
    old_dir = tmp_path / "Dune - Prophecy (2024) {tvdb-367118}"
    old_dir.mkdir()
    old = old_dir / "poster.jpg"
    old.write_bytes(b"x")
    new = tmp_path / "Dune Prophecy (2024) {tvdb-367118}" / "poster.jpg"
    m._remove_superseded(str(old), str(new))
    assert not old.exists()
    assert not old_dir.exists()  # emptied folder is removed too


def test_remove_superseded_keeps_shared_folder_until_empty(tmp_path):
    """A season poster left in the old folder keeps the folder until the last
    file is gone."""
    m = _staging_module(destination_dir=str(tmp_path))
    old_dir = tmp_path / "Show - X (2024) {tvdb-1}"
    old_dir.mkdir()
    (old_dir / "poster.jpg").write_bytes(b"x")
    (old_dir / "Season01.jpg").write_bytes(b"x")
    m._remove_superseded(
        str(old_dir / "poster.jpg"),
        str(tmp_path / "Show X (2024) {tvdb-1}" / "poster.jpg"),
    )
    assert old_dir.exists()  # Season01.jpg still there
    assert (old_dir / "Season01.jpg").exists()


def test_remove_superseded_ignores_paths_outside_destination(tmp_path):
    """Never delete outside the staging tree, even if asked."""
    m = _staging_module(destination_dir=str(tmp_path / "assets"))
    (tmp_path / "assets").mkdir()
    outside = tmp_path / "elsewhere.jpg"
    outside.write_bytes(b"x")
    m._remove_superseded(str(outside), str(tmp_path / "assets" / "poster.jpg"))
    assert outside.exists()  # untouched


# --- skip-unchanged plex fast-path (_is_unchanged_upload / _source_hash) ---


def test_source_hash_reads_and_missing_is_none(tmp_path):
    m = make_module()
    src = tmp_path / "poster.jpg"
    src.write_bytes(b"POSTER-BYTES-V1")
    h = m._source_hash(str(src))
    assert h and len(h) == 64
    assert m._source_hash(str(tmp_path / "gone.jpg")) is None


def _plex_cfg(**over):
    base = dict(apply_method="plex", skip_unchanged_uploads=True)
    base.update(over)
    return SimpleNamespace(**base)


def test_is_unchanged_upload_skips_when_source_matches(tmp_path):
    m = make_module()
    m.config = _plex_cfg()
    src = tmp_path / "p.jpg"
    src.write_bytes(b"V1")
    h = m._source_hash(str(src))
    row = {
        "original_file": str(src),
        "source_file_hash": h,
        "uploaded_libraries": '["Movies"]',
    }
    assert m._is_unchanged_upload(row) is True

    # Source changed on disk -> hash mismatch -> not skipped.
    src.write_bytes(b"V2-different")
    assert m._is_unchanged_upload(row) is False


def test_is_unchanged_upload_fail_safe_cases(tmp_path):
    m = make_module()
    src = tmp_path / "p.jpg"
    src.write_bytes(b"V1")
    h = m._source_hash(str(src))
    row = {
        "original_file": str(src),
        "source_file_hash": h,
        "uploaded_libraries": '["L"]',
    }

    # kometa path never skips (no plex upload record to trust)
    m.config = _plex_cfg(apply_method="kometa")
    assert m._is_unchanged_upload(row) is False

    # feature disabled
    m.config = _plex_cfg(skip_unchanged_uploads=False)
    assert m._is_unchanged_upload(row) is False

    m.config = _plex_cfg()
    # never uploaded before (no uploaded_libraries) -> must process
    assert m._is_unchanged_upload({**row, "uploaded_libraries": None}) is False
    # no stored source signature -> must process
    assert m._is_unchanged_upload({**row, "source_file_hash": None}) is False
    # source file gone -> fail safe, process (never a silent skip)
    assert (
        m._is_unchanged_upload({**row, "original_file": str(tmp_path / "x.jpg")})
        is False
    )


# --- library-aware skip: uploaded_libraries must cover current targets ---


def _movie_lib_index(*libraries):
    from backend.util.plex_index import PlexMediaIndex

    rows = [
        {
            "asset_type": "movie",
            "title": "Dune",
            "normalized_title": "dune",
            "library_name": lib,
            "guids": {"tmdb": "1"},
        }
        for lib in libraries
    ]
    return PlexMediaIndex(rows)


def _unchanged_movie_row(tmp_path, uploaded_libraries):
    m = make_module()
    m.config = _plex_cfg()
    src = tmp_path / "p.jpg"
    src.write_bytes(b"V1")
    row = {
        "asset_type": "movie",
        "title": "Dune",
        "tmdb_id": 1,
        "original_file": str(src),
        "source_file_hash": m._source_hash(str(src)),
        "uploaded_libraries": uploaded_libraries,
    }
    return m, row


def test_is_unchanged_upload_backfills_new_library(tmp_path):
    """A currently-targeted library the poster hasn't reached (new opt-in or a
    partial per-library failure) must re-flow to the uploader's backfill; full
    coverage keeps the fast-path skip."""
    m, row = _unchanged_movie_row(tmp_path, '["Movies"]')
    idx = _movie_lib_index("Movies", "Movies 4K")
    assert m._is_unchanged_upload(row, [idx]) is False

    row["uploaded_libraries"] = '["Movies", "Movies 4K"]'
    assert m._is_unchanged_upload(row, [idx]) is True


def test_is_unchanged_upload_skips_when_item_not_in_snapshot(tmp_path):
    """Resolver miss (item absent from every enabled snapshot) keeps the skip
    — the uploader could only fail with 'No matching Plex entry found'."""
    m, row = _unchanged_movie_row(tmp_path, '["Movies"]')
    assert m._is_unchanged_upload(row, [_movie_lib_index()]) is True
    assert m._is_unchanged_upload(row, []) is True


def test_is_unchanged_upload_none_indexes_preserves_legacy(tmp_path):
    m, row = _unchanged_movie_row(tmp_path, '["Movies"]')
    assert m._is_unchanged_upload(row, None) is True
    assert m._is_unchanged_upload(row) is True


# --- adhoc match runs under the rebuild lock (webhook clear() race) ---


def test_adhoc_match_runs_under_rebuild_lock(monkeypatch):
    """A second webhook worker's clear() must not empty poster_cache mid-match:
    the adhoc rebuild lock has to still be held while match_item reads it."""
    from backend.modules import poster_renamerr as pr_mod

    class _StubLogger:
        def __getattr__(self, _name):
            return lambda *a, **kw: None

        def get_adapter(self, *a, **kw):
            return self

    class _StubDB:
        def __init__(self, *a, **kw):
            self.poster = SimpleNamespace(clear=lambda: None)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pr_mod, "ChubDB", _StubDB)

    m = object.__new__(PosterRenamerr)
    m.logger = _StubLogger()
    m.full_config = None
    m.ensure_destination_dir = lambda: None
    m._scan_source_dirs = lambda: []
    m.merge_assets = lambda **kw: None
    m.merge_gdrive_search_index = lambda db: None

    observed = []

    def _match_stub(media_item, db, is_collection=False):
        acquired = pr_mod._POSTER_CACHE_REBUILD_LOCK.acquire(blocking=False)
        if acquired:
            pr_mod._POSTER_CACHE_REBUILD_LOCK.release()
        observed.append(acquired)
        return {"matched": False}

    m.match_item = _match_stub

    result = m.run_poster_rename_adhoc([{"asset_type": "movie", "id": 1}])
    assert result["success"] is True
    assert observed == [False], "match_item ran without the rebuild lock held"


# --- _build_plex_notify_output (plex-path notification payload) ---


def test_build_plex_notify_output_lists_only_genuine_uploads():
    """The plex-path notification is built from the uploader's payload
    ("uploaded" = action=='updated' only) — staged/skipped/failed posters must
    never appear, so re-flow retries can't spam every scheduled run."""
    upload_result = {
        "success": True,
        "payload": {
            "updated": 3,
            "skipped": 40,
            "failed": 2,
            "uploaded": [
                {
                    "title": "Film",
                    "year": "2026",
                    "asset_type": "movie",
                    "season_number": None,
                    "library_name": "Movies, Movies 4K",
                    "instance": "plex_main",
                },
                {
                    "title": "Show",
                    "year": 2020,
                    "asset_type": "show",
                    "season_number": 2,
                    "library_name": "TV",
                    "instance": "plex_main",
                },
                {
                    "title": "Queen",
                    "year": None,
                    "asset_type": "artist",
                    "season_number": None,
                    "library_name": "Music",
                    "instance": "plex_main",
                },
            ],
        },
    }
    out = PosterRenamerr._build_plex_notify_output(upload_result)
    assert [a["title"] for a in out["movie"]] == ["Film"]
    assert out["movie"][0]["messages"] == ["Uploaded to Movies, Movies 4K"]
    assert out["show"][0]["messages"] == ["Season 02 uploaded to TV"]
    assert out["artist"][0]["title"] == "Queen"
    assert out["collection"] == [] and out["album"] == []


def test_build_plex_notify_output_empty_and_none_are_all_empty():
    """Zero genuine uploads (steady state) and a missing/failed upload result
    both produce the all-empty shape — the caller then sends the one-line
    heartbeat instead of a poster list."""
    empty = PosterRenamerr._build_plex_notify_output(
        {"success": True, "payload": {"uploaded": []}}
    )
    assert not any(empty.values())
    assert not any(PosterRenamerr._build_plex_notify_output(None).values())
    assert not any(PosterRenamerr._build_plex_notify_output({}).values())



# --- ensure_destination_dir ---


def test_ensure_destination_dir_reports_an_unmountable_path(tmp_path):
    """A bare OSError reads as "[Errno 20] Not a directory" with no hint that the
    volume simply isn't mounted, and the caller logs whatever message it gets.

    A plain file standing where a parent directory should be reproduces the real
    failure without patching os.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a mount point")

    m = make_module()
    m.config = SimpleNamespace(destination_dir=str(blocker / "assets"))
    with pytest.raises(FileNotFoundError, match="volume is mounted"):
        m.ensure_destination_dir()


def test_ensure_destination_dir_tolerates_a_concurrent_create(tmp_path):
    """Two passes can race between the isdir() check and makedirs()."""
    m = make_module()
    dest = tmp_path / "dest"
    m.config = SimpleNamespace(destination_dir=str(dest))
    m.ensure_destination_dir()
    m.ensure_destination_dir()  # already there now — must not raise
    assert dest.is_dir()

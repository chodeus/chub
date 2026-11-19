"""Tests for backend/modules/poster_renamerr.py — asset classifier + walk behavior.

Targets the behavior introduced in commit 57cd537 ("Improve poster asset
matching and cache handling"), specifically:

* ``_classify_asset_record`` — pure decision: movie / show / collection
* ``_get_assets_files`` — strips season tokens from titles, sorts walk
  output deterministically, and post-classifies records using sibling
  show_keys so e.g. a "Show (2020)" main poster sitting next to "Show
  (2020) - Season 01.jpg" gets classified as ``show``, not ``movie``.
"""

import errno
import json
import os
import sqlite3
import threading
from types import SimpleNamespace

import pytest


from backend.modules.poster_renamerr import PosterRenamerr
from backend.util.connector import SyncResult
from backend.util.database import ChubDB


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


def _insert_media_row(db, identity_key: str, sql_values: str) -> dict:
    """Insert one media_cache row (values after identity_key, as SQL) and read it back."""
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,"
        f"tmdb_id,tvdb_id,imdb_id,instance_name) VALUES ('{identity_key}',{sql_values})"
    )
    return dict(
        db.media.execute_query(
            "SELECT * FROM media_cache WHERE identity_key=?",
            (identity_key,),
            fetch_one=True,
        )
    )


def _insert_poster(db, sql_columns: str, sql_values: str) -> None:
    db.poster.execute_query(
        f"INSERT INTO poster_cache ({sql_columns}) VALUES ({sql_values})"
    )


def test_match_item_bottom_wins_across_id_fields(tmp_path):
    """Id hits from different fields are ranked together: the drive further down the source list wins."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,imdb_id,file,priority) "
            "VALUES ('show','Monster The Lizzie Borden Story','monsterthelizziebordenstory',2026,"
            "299939,'tt13207736','/Bostafari/Monster The Lizzie Borden Story (2026).jpg',26)"
        )
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tvdb_id,file,priority) "
            "VALUES ('show','Monster','monster',2022,389492,'/Dweagle79/Monster (2022).jpg',40)"
        )
        media = _insert_media_row(
            db,
            "mk",
            "'show','Monster','monster','2022',113988,389492,'tt13207736','sonarr'",
        )
        m.match_item(media, db)
        updated = db.media.get_by_id(media["id"])
        assert updated["original_file"] == "/Dweagle79/Monster (2022).jpg"
        # Both posters are tied to the item by an id, so their titles never conflict.
        assert updated["match_status"] == "matched"
        assert updated["conflict_ids"] == "[]"
    finally:
        db.__exit__(None, None, None)


def test_match_item_bottom_wins_over_an_id_hit_from_a_higher_drive(tmp_path):
    """A same-title poster with a year but no ids on a lower drive beats an id-tagged one above it."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,tmdb_id,file,priority) "
            "VALUES ('movie','Inception','inception',2010,27205,'/top/Inception (2010).jpg',0)"
        )
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year,file,priority) "
            "VALUES ('movie','Inception','inception',2010,'/bottom/Inception (2010).jpg',1)"
        )
        media = _insert_media_row(
            db, "mk", "'movie','Inception','inception','2010',27205,NULL,NULL,'radarr'"
        )
        m.match_item(media, db)
        updated = db.media.get_by_id(media["id"])
        assert updated["original_file"] == "/bottom/Inception (2010).jpg"
        assert updated["match_status"] == "matched"
    finally:
        db.__exit__(None, None, None)


def test_match_item_id_hit_wins_a_tie_on_the_same_drive(tmp_path):
    """On one drive an id-tagged poster beats a newer same-titled variant without ids."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,tmdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'movie','Inception','inception',2010,27205,'/d/Inception (2010) {tmdb-27205}.jpg',4",
        )
        _insert_poster(
            db,
            cols,
            "'movie','Inception','inception',2010,NULL,'/d/Inception (2010).jpg',4",
        )
        media = _insert_media_row(
            db, "mk", "'movie','Inception','inception','2010',27205,NULL,NULL,'radarr'"
        )
        m.match_item(media, db)
        assert (
            db.media.get_by_id(media["id"])["original_file"]
            == "/d/Inception (2010) {tmdb-27205}.jpg"
        )
    finally:
        db.__exit__(None, None, None)


def test_match_item_yearless_title_poster_never_beats_an_id_hit(tmp_path):
    """A poster with no year and no ids on a lower drive loses to an id-tagged one above it."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        _insert_poster(
            db,
            "asset_type,title,normalized_title,year,tvdb_id,file,priority",
            "'show','The Office','theoffice',2005,73244,'/top/The Office (2005) {tvdb-73244}.jpg',0",
        )
        _insert_poster(
            db,
            "asset_type,title,normalized_title,file,priority",
            "'show','The Office','theoffice','/bottom/The Office.jpg',1",
        )
        media = _insert_media_row(
            db,
            "mk",
            "'show','The Office','theoffice','2005',2316,73244,'tt0386676','sonarr'",
        )
        m.match_item(media, db)
        assert (
            db.media.get_by_id(media["id"])["original_file"]
            == "/top/The Office (2005) {tvdb-73244}.jpg"
        )
    finally:
        db.__exit__(None, None, None)


def test_match_item_alternate_title_poster_beside_an_id_hit_is_no_conflict(tmp_path):
    """An id-matched poster and an alternate-title poster of the same film are not rivals."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        _insert_poster(
            db,
            "asset_type,title,normalized_title,year,tmdb_id,file,priority",
            "'movie','Amelie','amelie',2001,194,'/top/Amelie (2001) {tmdb-194}.jpg',0",
        )
        _insert_poster(
            db,
            "asset_type,title,normalized_title,year,file,priority",
            "'movie','Le Fabuleux Destin','lefabuleuxdestin',2001,'/bottom/Le Fabuleux Destin (2001).jpg',1",
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,year,tmdb_id,"
            "alternate_titles,normalized_alternate_titles,instance_name) VALUES "
            "('mk','movie','Amelie','amelie','2001',194,'[\"Le Fabuleux Destin\"]','[\"lefabuleuxdestin\"]','radarr')"
        )
        media = dict(
            db.media.execute_query(
                "SELECT * FROM media_cache WHERE identity_key='mk'", fetch_one=True
            )
        )
        m.match_item(media, db)
        updated = db.media.get_by_id(media["id"])
        assert updated["original_file"] == "/bottom/Le Fabuleux Destin (2001).jpg"
        assert updated["match_status"] == "matched"
        assert updated["conflict_ids"] == "[]"
    finally:
        db.__exit__(None, None, None)


def test_title_lookup_skips_posters_ranked_at_or_below_the_id_floor(tmp_path):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        for p in (0, 1, 2):
            _insert_poster(
                db,
                "asset_type,title,normalized_title,file,priority",
                f"'movie','Heat','heat','/{p}/Heat.jpg',{p}",
            )
        rows = db.poster.get_candidates_by_prefix(
            "Heat", asset_type="movie", above_priority=1
        )
        assert [r["file"] for r in rows] == ["/2/Heat.jpg"]
    finally:
        db.__exit__(None, None, None)


def test_title_prefix_lookup_returns_only_titles_starting_with_the_prefix(tmp_path):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        for t, kind in (
            ("ab", "movie"),
            ("abb~", "movie"),
            ("abc", "movie"),
            ("abcz", "movie"),
            ("abd", "movie"),
            ("abcq", "show"),
        ):
            _insert_poster(
                db,
                "asset_type,title,normalized_title,file",
                f"'{kind}','{t}','{t}','/{t}.jpg'",
            )
        rows = db.poster.get_candidates_by_prefix("Abc", asset_type="movie")
        assert sorted(r["normalized_title"] for r in rows) == ["abc", "abcz"]
    finally:
        db.__exit__(None, None, None)


def test_title_prefix_lookup_searches_the_title_index(tmp_path, monkeypatch):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        real, calls = db.poster.execute_query, []
        monkeypatch.setattr(
            db.poster,
            "execute_query",
            lambda sql, params=(), **kw: (
                calls.append((sql, params)) or real(sql, params, **kw)
            ),
        )
        db.poster.get_candidates_by_prefix("Heat", asset_type="movie", above_priority=0)
        sql, params = calls[-1]
        plan = [
            r["detail"]
            for r in real("EXPLAIN QUERY PLAN " + sql, tuple(params), fetch_all=True)
        ]
        assert any(
            "USING INDEX poster_cache_normalized_title_idx" in d for d in plan
        ), plan
    finally:
        db.__exit__(None, None, None)


def test_match_rank_puts_a_loose_match_below_a_firm_one():
    """A loose title match on the bottom drive loses to an exact yeared title and an id hit above it."""
    loose = (
        {"file": "/bottom/x.jpg", "priority": 9, "id": 2, "year": 2010},
        "Titles match under loose string comparison",
    )
    exact = (
        {"file": "/top/x.jpg", "priority": 0, "id": 1, "year": 2010},
        "Asset title equals media title",
    )
    by_id = (
        {"file": "/mid/x.jpg", "priority": 5, "id": 3, "year": None},
        "ID match: tvdb_id",
    )
    ranked = sorted(
        [loose, exact, by_id],
        key=lambda p: PosterRenamerr._match_rank(p, beside_id_hit=True),
        reverse=True,
    )
    assert [p["file"] for p, _ in ranked] == [
        "/mid/x.jpg",
        "/top/x.jpg",
        "/bottom/x.jpg",
    ]


def _season_media(db, key: str, sql_values: str, season: int) -> dict:
    _insert_media_row(db, key, sql_values)
    db.media.execute_query(
        "UPDATE media_cache SET season_number=? WHERE identity_key=?", (season, key)
    )
    return dict(
        db.media.execute_query(
            "SELECT * FROM media_cache WHERE identity_key=?", (key,), fetch_one=True
        )
    )


def test_match_item_yearless_title_poster_on_a_lower_drive_wins_without_an_id_hit(
    tmp_path,
):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,season_number,file,priority"
        _insert_poster(
            db,
            cols,
            "'show','Breaking Bad','breakingbad',2008,1,'/top/Breaking Bad (2008) - Season 1.jpg',0",
        )
        _insert_poster(
            db,
            cols,
            "'show','Breaking Bad','breakingbad',NULL,1,'/bottom/Breaking Bad - Season 1.jpg',1",
        )
        media = _season_media(
            db,
            "bb",
            "'show','Breaking Bad','breakingbad','2008',NULL,81189,NULL,'sonarr'",
            1,
        )
        m.match_item(media, db)
        assert (
            db.media.get_by_id(media["id"])["original_file"]
            == "/bottom/Breaking Bad - Season 1.jpg"
        )
    finally:
        db.__exit__(None, None, None)


def test_match_item_title_poster_contradicting_an_id_hit_does_not_win(tmp_path):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,tvdb_id,tmdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'show','Ghosts','ghosts',2021,389963,118357,'/top/Ghosts (2021) {tvdb-389963}.jpg',0",
        )
        _insert_poster(
            db,
            cols,
            "'show','Ghosts','ghosts',2020,NULL,88528,'/bottom/Ghosts (2020) {tmdb-88528}.jpg',1",
        )
        media = _insert_media_row(
            db, "gh", "'show','Ghosts','ghosts','2021',NULL,389963,NULL,'sonarr'"
        )
        m.match_item(media, db)
        row = db.media.get_by_id(media["id"])
        assert (row["original_file"], row["match_status"]) == (
            "/top/Ghosts (2021) {tvdb-389963}.jpg",
            "matched",
        )
    finally:
        db.__exit__(None, None, None)


@pytest.mark.parametrize(
    "media_year,second_id,expected",
    [
        ("2020", "tmdb_id", "needs_review"),
        ("NULL", "tmdb_id", "needs_review"),
        ("2020", "tvdb_id", "matched"),
    ],
    ids=["two-id-hits", "tmdb-row-on-title", "other-id-fields"],
)
def test_match_item_flags_an_id_hit_setting_another_value_for_the_same_id(
    tmp_path, media_year, second_id, expected
):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = f"asset_type,title,normalized_title,year,imdb_id,{second_id},file,priority"
        _insert_poster(
            db,
            cols,
            "'movie','Harbor Lights','harborlights',2020,'tt0000101',202,'/a/Harbor Lights (2020).jpg',0",
        )
        cols = "asset_type,title,normalized_title,year,tmdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'movie','Harbor Lights','harborlights',2020,101,'/b/Harbor Lights (2020).jpg',1",
        )
        media = _insert_media_row(
            db,
            "hl",
            f"'movie','Harbor Lights','harborlights',{media_year},101,NULL,'tt0000101','radarr'",
        )
        m.match_item(media, db)
        row = db.media.get_by_id(media["id"])
        flagged = [c["file"] for c in json.loads(row["conflict_ids"])]
        assert (row["original_file"], row["match_status"], flagged) == (
            "/b/Harbor Lights (2020).jpg",
            expected,
            ["/b/Harbor Lights (2020).jpg", "/a/Harbor Lights (2020).jpg"]
            if expected == "needs_review"
            else [],
        )
    finally:
        db.__exit__(None, None, None)


@pytest.mark.parametrize("distinct_titles", [False, True], ids=["same-title", "five-titles"])
def test_match_item_keeps_a_rival_ranked_past_five_in_conflict_ids(
    tmp_path, distinct_titles
):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,imdb_id,tmdb_id,file,priority"
        for p in range(6, 11):
            suffix = f" {p}" if distinct_titles else ""
            _insert_poster(
                db,
                cols,
                f"'movie','Harbor Lights{suffix}','harborlights{suffix.strip()}',2020,NULL,101,'/d{p}/Harbor Lights (2020).jpg',{p}",
            )
        _insert_poster(
            db,
            cols,
            "'movie','Harbor Lights','harborlights',2020,'tt0000101',202,'/d0/Harbor Lights (2020).jpg',0",
        )
        media = _insert_media_row(
            db,
            "hl",
            "'movie','Harbor Lights','harborlights','2020',101,NULL,'tt0000101','radarr'",
        )
        m.match_item(media, db)
        row = db.media.get_by_id(media["id"])
        flagged = [c["file"].split("/")[1] for c in json.loads(row["conflict_ids"])]
        assert (row["match_status"], flagged) == (
            "needs_review",
            ["d10", "d9", "d8", "d7", "d0"],
        )
    finally:
        db.__exit__(None, None, None)


def test_find_asset_candidate_queries_each_title_prefix_once(tmp_path, monkeypatch):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,tvdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'show','The Office','theoffice',2005,73244,'/d/The Office (2005) {tvdb-73244}.jpg',0",
        )
        alts = ["The Office US", "The Office (US)", "Office", "The Office USA"]
        media = {
            "asset_type": "show",
            "title": "The Office",
            "normalized_title": "theoffice",
            "year": 2005,
            "tvdb_id": 73244,
            "season_number": None,
            "alternate_titles": json.dumps(alts),
        }
        real, calls = db.poster.get_candidates_by_prefix, []
        monkeypatch.setattr(
            db.poster,
            "get_candidates_by_prefix",
            lambda t, **kw: calls.append(t) or real(t, **kw),
        )
        found = PosterRenamerr.find_asset_candidate(media, db)
        assert (found["candidate"]["file"], calls) == (
            "/d/The Office (2005) {tvdb-73244}.jpg",
            ["The Office", "Office"],
        )
    finally:
        db.__exit__(None, None, None)


def test_match_item_loose_tmdb_row_sets_no_floor_over_a_title_poster(tmp_path):
    """A tmdb row that only passed on a loose title is no id hit, so it sets no floor."""
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,tmdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'movie','Fast Furious','fastfurious',NULL,13804,'/low/Fast Furious.jpg',5",
        )
        _insert_poster(
            db,
            cols,
            "'movie','Fast & Furious','fastandfurious',2009,NULL,'/high/Fast & Furious (2009).jpg',3",
        )
        media = _insert_media_row(
            db,
            "ff",
            "'movie','Fast & Furious','fastandfurious','2009',13804,NULL,NULL,'radarr'",
        )
        m.match_item(media, db)
        row = db.media.get_by_id(media["id"])
        assert row["original_file"] == "/high/Fast & Furious (2009).jpg"
    finally:
        db.__exit__(None, None, None)


def test_match_item_aka_title_posters_beside_an_id_hit_are_not_a_conflict(tmp_path):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,year,imdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'movie','Inception','inception',2010,'tt1375666','/a/Inception (2010) {imdb-tt1375666}.jpg',1",
        )
        _insert_poster(
            db, cols, "'movie','Inception','inception',NULL,NULL,'/b/Inception.jpg',3"
        )
        _insert_poster(
            db, cols, "'movie','Origen','origen',NULL,NULL,'/b/Origen.jpg',3"
        )
        _insert_media_row(
            db,
            "inc",
            "'movie','Inception','inception','2010',NULL,NULL,'tt1375666','radarr'",
        )
        db.media.execute_query(
            "UPDATE media_cache SET alternate_titles=?, normalized_alternate_titles=? WHERE identity_key='inc'",
            ('["Origen"]', '["origen"]'),
        )
        media = dict(
            db.media.execute_query(
                "SELECT * FROM media_cache WHERE identity_key='inc'", fetch_one=True
            )
        )
        m.match_item(media, db)
        row = db.media.get_by_id(media["id"])
        assert (row["original_file"], row["match_status"], row["conflict_ids"]) == (
            "/a/Inception (2010) {imdb-tt1375666}.jpg",
            "matched",
            "[]",
        )
    finally:
        db.__exit__(None, None, None)


def test_find_asset_candidate_skips_alternate_titles_that_are_not_strings(tmp_path):
    m = make_module()
    db = _open_db(tmp_path, m.logger)
    try:
        cols = "asset_type,title,normalized_title,tmdb_id,file,priority"
        _insert_poster(
            db,
            cols,
            "'collection','Alien Collection','aliencollection',8091,'/d/Alien Collection {tmdb-8091}.jpg',0",
        )
        for stored in ('[123, null, "Alien Saga"]', '{"a": 1}', '"Alien"'):
            media = {
                "asset_type": "collection",
                "title": "Alien Collection",
                "normalized_title": "aliencollection",
                "tmdb_id": 8091,
                "season_number": None,
                "alternate_titles": stored,
            }
            found = PosterRenamerr.find_asset_candidate(media, db, is_collection=True)
            assert (
                found["candidate"]["file"] == "/d/Alien Collection {tmdb-8091}.jpg"
            ), stored
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

    db = SimpleNamespace(collection=_Iface(), media=_Iface(), records_placed_path=lambda path: False)
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
        action_type="copy",
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


@pytest.mark.parametrize("apply_method, restage", [("kometa", True), ("plex", False)])
def test_a_staged_link_is_restaged_only_where_kometa_reads_it(tmp_path, apply_method, restage):
    m = _staging_module(destination_dir=str(tmp_path))
    m.config.apply_method = apply_method
    folder = "Dune (2021) {tmdb-1}"
    (tmp_path / folder).mkdir()
    src = tmp_path / "Dune.jpg"
    src.write_bytes(b"x")
    staged = tmp_path / folder / "poster.jpg"
    staged.symlink_to(src)
    row = {"asset_type": "movie", "matched": 1, "folder": folder, "original_file": str(src), "season_number": None}
    needs = m._needs_staging(dict(row, renamed_file=str(staged)))
    assert needs is restage


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


def test_remove_superseded_drops_old_folder(tmp_path, db):
    """Re-staging after a folder rename removes the stale file and its now-empty
    old folder — Kometa ignores it and the orphan pass spares its id, so it
    would otherwise linger forever."""
    m = _staging_module(destination_dir=str(tmp_path))
    old_dir = tmp_path / "Dune - Prophecy (2024) {tvdb-367118}"
    old_dir.mkdir()
    old = old_dir / "poster.jpg"
    old.write_bytes(b"x")
    new = tmp_path / "Dune Prophecy (2024) {tvdb-367118}" / "poster.jpg"
    m._remove_superseded(str(old), str(new), db)
    assert not old.exists()
    assert not old_dir.exists()  # emptied folder is removed too


def test_remove_superseded_keeps_shared_folder_until_empty(tmp_path, db):
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
        db,
    )
    assert old_dir.exists()  # Season01.jpg still there
    assert (old_dir / "Season01.jpg").exists()


@pytest.fixture
def db(tmp_path, stub_logger):
    with ChubDB(stub_logger, db_path=str(tmp_path / "chub.db"), quiet=True) as database:
        yield database


@pytest.mark.parametrize("action_type", ["copy", "move"])
@pytest.mark.parametrize("shared", [True, False], ids=["shared", "own"])
def test_a_renamed_poster_leaves_the_old_file_only_while_another_row_records_it(tmp_path, db, shared, action_type):
    src = tmp_path / "src" / "Dune (2021).jpg"
    src.parent.mkdir()
    if action_type == "copy":
        src.write_bytes(b"poster")  # under move the source is gone: the staged file is carried
    kometa = tmp_path / "kometa"
    old = kometa / "Dune (2021)" / "poster.jpg"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"poster")
    m = make_module()
    m.config = SimpleNamespace(
        destination_dir=str(kometa), asset_folders=True, dry_run=False, action_type=action_type,
        run_border_replacerr=False, print_only_renames=False,
    )
    for instance, folder in [("radarr-4k", "Dune (2021) {edition-4K}")] + [("radarr-hd", "Dune (2021)")] * shared:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key, instance_name, folder, asset_type, title, year, renamed_file)"
            " VALUES (?,?,?,?,?,?,?)",
            (f"{instance}|{folder}|None", instance, folder, "movie", "Dune", 2021, str(old)),
        )
    row = db.media.execute_query("SELECT * FROM media_cache WHERE instance_name='radarr-4k'", fetch_one=True)
    m.rename_file(dict(row, original_file=str(src)), db)
    assert (old.exists(), (kometa / "Dune (2021) {edition-4K}" / "poster.jpg").read_bytes()) == (shared, b"poster")


@pytest.mark.parametrize("holder, recorded", [("collection", True), ("deleted item's asset", False)])
def test_records_placed_path_reads_collections_and_only_live_items_assets(db, holder, recorded):
    path = "/kometa/Marvel.jpg"
    if holder == "collection":
        db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")
        db.collection.set_renamed_file(db.collection.get_by_title_and_instance("Marvel", "plex1", "Movies")["id"], path)
    else:
        db.media_asset_matches.upsert(
            target_kind="media", target_id=99, image_type="logo", source="local", matched_file=path,
            applied_method="kometa", applied_path=path, match_status="applied",
        )
    found = db.records_placed_path(path)
    assert found is recorded


@pytest.mark.parametrize("step", ["query", "schema"])
def test_a_failed_placed_path_check_keeps_the_file(db, monkeypatch, stub_logger, step):
    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    target, name = (db.media, "execute_query") if step == "query" else (db, "_ensure_initialized")
    monkeypatch.setattr(target, name, locked)
    kept = db.records_placed_path("/kometa/Dune (2021)/poster.jpg")
    assert (kept, stub_logger.messages["warning"]) == (
        True,
        ["Keeping /kometa/Dune (2021)/poster.jpg: could not check whether a row records it: database is locked"],
    )


def test_remove_superseded_keeps_the_poster_both_paths_name(tmp_path, db):
    real = tmp_path / "posters"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real)
    poster = real / "Dune (2021).jpg"
    poster.write_bytes(b"x")
    m = _staging_module(destination_dir=str(real))
    m._remove_superseded(str(tmp_path / "alias" / "Dune (2021).jpg"), str(poster), db)
    assert poster.read_bytes() == b"x"


def test_remove_superseded_ignores_paths_outside_destination(tmp_path, db):
    """Never delete outside the staging tree, even if asked."""
    m = _staging_module(destination_dir=str(tmp_path / "assets"))
    (tmp_path / "assets").mkdir()
    outside = tmp_path / "elsewhere.jpg"
    outside.write_bytes(b"x")
    m._remove_superseded(str(outside), str(tmp_path / "assets" / "poster.jpg"), db)
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


def test_a_failed_adhoc_rename_reports_only_the_kind(monkeypatch):
    """The ad-hoc result reaches the browser through the job APIs."""
    from backend.modules import poster_renamerr as pr_mod

    class _StubDB:
        def __init__(self, *a, **kw):
            self.poster = SimpleNamespace(clear=lambda: None)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pr_mod, "ChubDB", _StubDB)
    m = object.__new__(PosterRenamerr)
    m.logger = SimpleNamespace(
        error=lambda *a, **k: None, get_adapter=lambda *a, **k: m.logger
    )
    m.full_config = None

    def boom():
        raise RuntimeError("/srv/posters token=hunter2")

    m.ensure_destination_dir = boom

    result = m.run_poster_rename_adhoc([{"asset_type": "movie", "id": 1}])

    assert result == {
        "success": False,
        "message": "Poster rename failed: unexpected error — see the server log",
    }


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


# --- handle_output: music sections only when Lidarr is in scope ---


def _capture_module(instances, lidarr_names):
    m = make_module()
    lines = []
    m.logger = SimpleNamespace(
        debug=lambda *a, **kw: None,
        info=lambda msg="", *a, **kw: lines.append(str(msg)),
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    m.config = SimpleNamespace(instances=instances)
    m.full_config = SimpleNamespace(
        instances=SimpleNamespace(lidarr={n: object() for n in lidarr_names})
    )
    return m, lines


def test_handle_output_hides_music_sections_without_lidarr():
    m, lines = _capture_module(["Radarr", "Sonarr"], [])
    m.handle_output({"movie": [], "show": [], "collection": []})
    body = "\n".join(lines)
    assert "Artists" not in body and "Albums" not in body
    assert "Movies" in body  # non-music sections still render


def test_handle_output_shows_music_sections_with_lidarr():
    m, lines = _capture_module(["Radarr", "LidarrMain"], ["LidarrMain"])
    m.handle_output({"movie": [], "show": [], "collection": []})
    body = "\n".join(lines)
    assert "Artists" in body and "Albums" in body


def test_handle_output_never_hides_music_rows_that_exist():
    # Fail-safe: rows present but no Lidarr configured must still be shown.
    m, lines = _capture_module(["Radarr"], [])
    m.handle_output(
        {"movie": [], "album": [{"title": "The Wall", "year": 1979, "messages": ["x"]}]}
    )
    body = "\n".join(lines)
    assert "Albums" in body and "The Wall" in body

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


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_ensure_destination_dir_refuses_a_mount_it_cannot_write(tmp_path):
    """An existing but root-owned mount used to pass, so every poster failed on its own."""
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = make_module()
    m.config = SimpleNamespace(destination_dir=str(dest))
    dest.chmod(0o555)
    try:
        with pytest.raises(PermissionError) as raised:
            m.ensure_destination_dir()
        st = os.stat(dest)
    finally:
        dest.chmod(0o755)
    assert raised.value.strerror == (
        f"Cannot create files in {dest}: Permission denied (CHUB runs as "
        f"{os.getuid()}:{os.getgid()}; the folder is owned by {st.st_uid}:{st.st_gid}, "
        "dr-xr-xr-x). Check the volume's host path, and that the folder's owner "
        "matches PUID/PGID."
    )


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_ensure_destination_dir_lets_a_dry_run_use_a_read_only_mount(tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = make_module()
    m.config = SimpleNamespace(destination_dir=str(dest), dry_run=True)
    dest.chmod(0o555)
    try:
        m.ensure_destination_dir()
    finally:
        dest.chmod(0o755)


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_run_fails_the_job_when_the_destination_cannot_be_written(tmp_path, monkeypatch):
    """The refusal fails the run and is logged once."""
    from tests.conftest import StubLogger

    class _StubDB:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("backend.modules.poster_renamerr.ChubDB", _StubDB)
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = make_module()
    m.logger = StubLogger()
    m.config = SimpleNamespace(
        destination_dir=str(dest), apply_method="kometa", log_level="info"
    )
    dest.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            m.run()
    finally:
        dest.chmod(0o755)
    [logged] = m.logger.messages["error"]
    assert logged.startswith(
        f"\n\nAn error occurred: [Errno 13] Cannot create files in {dest}: "
        "Permission denied"
    )


def _poster_run_with_chained_assets(tmp_path, monkeypatch, sync=None):
    """Real PosterRenamerr.run() scanning, matching and renaming a real poster, then chaining the real AssetRenamerr."""
    from backend.util.config import ChubConfig
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    src, posters, logos = tmp_path / "src", tmp_path / "posters", tmp_path / "logos"
    for folder in (src, posters, logos):
        folder.mkdir()
    (src / "Dune (2021) {tmdb-438631}.jpg").write_bytes(b"poster")
    (src / "Dune (2021) {tmdb-438631} - Logo.png").write_bytes(b"logo")
    db_path = str(tmp_path / "chub.db")
    with ChubDB(StubLogger(), db_path=db_path) as db:
        db.media.upsert(
            {
                "title": "Dune",
                "normalized_title": "dune",
                "alternate_titles": "[]",
                "year": 2021,
                "tmdb_id": 438631,
                "folder": "Dune (2021)",
                "status": "released",
                "has_content": 1,
            },
            "movie",
            "radarr",
            "radarr1",
        )
    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(src)]
    cfg.poster_renamerr.destination_dir = str(posters)
    cfg.poster_renamerr.instances = ["radarr1"]
    cfg.poster_renamerr.run_asset_renamerr = True
    cfg.asset_renamerr.sources = ["local"]
    cfg.asset_renamerr.asset_types = ["logo"]
    cfg.asset_renamerr.apply_method = "kometa"
    cfg.asset_renamerr.destination_dir = str(logos)
    cfg.asset_renamerr.instances = ["radarr1"]
    live = {"config": cfg}
    monkeypatch.setattr("backend.util.base_module.load_config", lambda: live["config"])

    class _OpenDB:
        def __init__(self, *a, **k):
            self._ctx = ChubDB(StubLogger(), db_path=db_path)

        def __enter__(self):
            return self._ctx.__enter__()

        def __exit__(self, *a):
            return self._ctx.__exit__(*a)

    def _update_arr_database():
        if sync:
            sync(live)
        return [SyncResult(instance_name="radarr1", instance_type="radarr", success=True)]

    sent = []
    arr = SimpleNamespace(
        update_arr_database=_update_arr_database,
        update_collections_database=lambda: None,
    )
    monkeypatch.setattr("backend.modules.poster_renamerr.ChubDB", _OpenDB)
    monkeypatch.setattr("backend.modules.sync_gdrive.ChubDB", _OpenDB)
    monkeypatch.setattr("backend.modules.border_replacerr.ChubDB", _OpenDB)
    monkeypatch.setattr("backend.modules.poster_renamerr.Connector", lambda **k: arr)
    monkeypatch.setattr(
        "backend.modules.poster_renamerr.NotificationManager",
        lambda cfg, log, module_name=None: SimpleNamespace(
            send_notification=lambda out: sent.append(module_name)
        ),
    )
    return PosterRenamerr(logger=StubLogger()), sent, posters, logos


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_chained_asset_folder_it_cannot_write_stops_the_run_before_any_poster(
    tmp_path, monkeypatch
):
    """No poster is written and no notification sent; the run fails naming the asset folder."""
    m, sent, posters, logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    logos.chmod(0o555)
    try:
        with pytest.raises(PermissionError) as raised:
            m.run()
        st = os.stat(logos)
    finally:
        logos.chmod(0o755)

    assert str(raised.value) == (
        f"[Errno 13] Cannot create files in {logos}: Permission denied (CHUB runs as "
        f"{os.getuid()}:{os.getgid()}; the folder is owned by {st.st_uid}:{st.st_gid}, "
        "dr-xr-xr-x). Check the volume's host path, and that the folder's owner "
        "matches PUID/PGID."
    )
    assert (os.listdir(posters), sent) == ([], [])


def test_chained_assets_on_writable_folders_notify_both_modules(tmp_path, monkeypatch):
    m, sent, posters, logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.run()
    assert os.listdir(posters) == ["Dune (2021).jpg"]
    assert os.listdir(logos) == ["Dune (2021)_logo.png"]
    assert sent == ["poster_renamerr", "asset_renamerr"]


_KEPT_HINT = (
    "Set File Action to copy, or let CHUB delete files in the source folder "
    "(a read/write mount, owned by PUID/PGID)."
)


def _pick_dune_poster(tmp_path, monkeypatch, action_type, link_fails_once=False):
    """A run places Dune's poster, then the poster picker applies a new one; returns (module, picked, placed, reply)."""
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.run()
    m.config.action_type = action_type
    if link_fails_once:
        name = "link" if action_type == "hardlink" else "symlink"
        real, calls = getattr(os, name), []

        def _fails_once(*a, **k):
            calls.append(a)
            if len(calls) == 1:
                raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
            return real(*a, **k)

        monkeypatch.setattr(os, name, _fails_once)
    picked, reply = _apply_dune_pick(tmp_path)
    assert os.listdir(posters) == ["Dune (2021).jpg"]
    return m, picked, posters / "Dune (2021).jpg", reply


def _apply_dune_pick(tmp_path):
    """The poster picker applies a new poster to Dune; returns (picked file, reply)."""
    from backend.api.posters.matching import apply_match
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    picked = tmp_path / "picks" / "Dune (2021).jpg"
    picked.parent.mkdir()
    picked.write_bytes(b"new poster")
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.poster.upsert(
            {
                "title": "Dune",
                "normalized_title": "dune",
                "year": 2021,
                "tmdb_id": 438631,
                "tvdb_id": None,
                "imdb_id": None,
                "season_number": None,
                "folder": str(picked.parent),
                "file": str(picked),
                "asset_type": "movie",
            }
        )
        poster_id = db.poster.execute_query(
            "SELECT id FROM poster_cache WHERE file=?", (str(picked),), fetch_one=True
        )["id"]
        resp = apply_match(media_id=1, poster_id=poster_id, kind="media", logger=StubLogger(), db=db)
    return picked, json.loads(resp.body)


_NOT_PLACED = "Match saved and locked — it will be applied on the next poster_renamerr run"


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_poster_it_could_not_place_fails_the_renamed_line(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.asset_folders = True
    folder = posters / "Dune (2021)"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        m.run()
    finally:
        folder.chmod(0o755)
    summary = _run_summary(m)
    [renamed] = [line for line in summary if line.startswith("Posters renamed")]
    assert (os.listdir(folder), renamed, summary[-1]) == (
        [],
        "Posters renamed  : ❌ 0 collections, 0 movies, 0 shows, 1 failed",
        "Result           : ⚠ finished, with failures above",
    )


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_pick_whose_new_folder_cannot_be_made_is_not_reported_as_copied(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.asset_folders = True
    m.run()
    old = posters / "Dune (2021)" / "poster.jpg"
    assert old.read_bytes() == b"poster"
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("Dune (2021) [renamed]",))
    posters.chmod(0o555)
    try:
        _picked, reply = _apply_dune_pick(tmp_path)
    finally:
        posters.chmod(0o755)
    assert (reply["data"]["copied"], reply["message"], old.read_bytes()) == (False, _NOT_PLACED, b"poster")


@pytest.mark.parametrize("action_type", ["hardlink", "symlink"])
def test_a_link_replaces_the_poster_already_there(tmp_path, monkeypatch, action_type):
    _m, picked, placed, reply = _pick_dune_poster(tmp_path, monkeypatch, action_type)
    assert (placed.read_bytes(), os.path.samefile(placed, picked)) == (b"new poster", True)
    assert (placed.is_symlink(), reply["data"]["copied"]) == (action_type == "symlink", True)


@pytest.mark.parametrize("action_type", ["hardlink", "symlink"])
def test_a_link_that_fails_keeps_the_old_poster_says_so_and_the_next_run_places_the_pick(
    tmp_path, monkeypatch, action_type
):
    m, picked, placed, reply = _pick_dune_poster(tmp_path, monkeypatch, action_type, link_fails_once=True)
    assert (placed.read_bytes(), reply["data"]["copied"], reply["message"]) == (b"poster", False, _NOT_PLACED)
    m.run()
    assert os.path.samefile(placed, picked)


def test_a_collection_poster_whose_link_failed_is_left_for_the_next_run(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    src, staged = tmp_path / "Marvel.jpg", tmp_path / "kometa" / "Marvel.jpg"
    staged.parent.mkdir()
    src.write_bytes(b"new poster")
    staged.write_bytes(b"poster")
    m = make_module()
    m.config = SimpleNamespace(
        destination_dir=str(staged.parent),
        asset_folders=False,
        dry_run=False,
        action_type="hardlink",
        run_border_replacerr=False,
        print_only_renames=False,
    )

    def _cross_device(*_a, **_k):
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))

    monkeypatch.setattr(os, "link", _cross_device)
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")
        row = db.collection.get_by_title_and_instance("Marvel", "plex1", "Movies")
        db.collection.update(
            title="Marvel", year=None, library_name="Movies", instance_name="plex1",
            renamed_file=str(staged), id=row["id"],
        )
        item = dict(db.collection.get_by_id(row["id"]), asset_type="collection", original_file=str(src))
        m.rename_file(item, db)
        after = db.collection.get_by_id(row["id"])
    assert (staged.read_bytes(), item["renamed_file"], after["renamed_file"]) == (b"poster", None, None)
    assert m._needs_staging(after)


@pytest.mark.parametrize("link", [os.link, os.symlink], ids=["hardlink", "symlink"])
def test_a_move_onto_a_link_to_its_source_removes_the_source(tmp_path, link):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    src, staged = tmp_path / "Marvel.jpg", tmp_path / "kometa" / "Marvel.jpg"
    staged.parent.mkdir()
    src.write_bytes(b"poster")
    link(src, staged)
    m = make_module()
    m.logger = StubLogger()
    m.config = SimpleNamespace(
        destination_dir=str(staged.parent),
        asset_folders=False,
        dry_run=False,
        action_type="move",
        run_border_replacerr=False,
        print_only_renames=False,
    )
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")
        row = db.collection.get_by_title_and_instance("Marvel", "plex1", "Movies")
        item = dict(db.collection.get_by_id(row["id"]), asset_type="collection", original_file=str(src))
        result = m.rename_file(item, db)
    assert (src.exists(), staged.is_symlink(), staged.read_bytes()) == (False, False, b"poster")
    assert result["messages"] == ["Marvel.jpg -not-renamed-> Marvel.jpg"]
    assert m.logger.messages["warning"] == []


def _dune_row(tmp_path):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        return db.media.get_by_id(1)


def _new_poster_folder(m, tmp_path):
    new_posters = tmp_path / "posters2"
    new_posters.mkdir()
    m.config.destination_dir = str(new_posters)
    return new_posters / "Dune (2021).jpg"


def test_a_poster_found_and_moved_follows_a_new_destination(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "move"
    m.run()
    placed = posters / "Dune (2021).jpg"
    src_left = (tmp_path / "src" / "Dune (2021) {tmdb-438631}.jpg").exists()
    assert (placed.read_bytes(), src_left) == (b"poster", False)
    landed = _new_poster_folder(m, tmp_path)
    m.run()
    assert (landed.read_bytes(), placed.exists(), _dune_row(tmp_path)["renamed_file"]) == (b"poster", False, str(landed))
    m.run()
    with open(landed, "rb") as f:
        kept = f.read()
    assert (kept, m.logger.messages["error"]) == (b"poster", [])


def test_a_poster_picked_with_move_follows_a_new_destination(tmp_path, monkeypatch):
    m, picked, placed, reply = _pick_dune_poster(tmp_path, monkeypatch, "move")
    assert (reply["data"]["copied"], picked.exists(), placed.read_bytes()) == (True, False, b"new poster")
    landed = _new_poster_folder(m, tmp_path)
    m.run()
    assert (landed.read_bytes(), placed.exists(), m.logger.messages["error"]) == (b"new poster", False, [])
    m.run()
    with open(landed, "rb") as f:
        kept = f.read()
    assert (kept, _dune_row(tmp_path)["renamed_file"]) == (b"new poster", str(landed))


def _moved_into_asset_folders(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "move"
    m.config.asset_folders = True
    m.run()
    return m, posters / "Dune (2021)" / "poster.jpg"


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_moved_poster_that_cannot_reach_a_new_destination_is_retried(tmp_path, monkeypatch):
    m, placed = _moved_into_asset_folders(tmp_path, monkeypatch)
    blocked = tmp_path / "posters2" / "Dune (2021)"
    blocked.mkdir(parents=True)
    m.config.destination_dir = str(blocked.parent)
    blocked.chmod(0o555)
    try:
        m.run()
    finally:
        blocked.chmod(0o755)
    assert (placed.read_bytes(), _dune_row(tmp_path)["renamed_file"]) == (b"poster", str(placed))
    m.run()
    assert ((blocked / "poster.jpg").read_bytes(), placed.exists()) == (b"poster", False)


def test_a_stale_run_on_a_moved_poster_keeps_its_staged_path(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, placed = _moved_into_asset_folders(tmp_path, monkeypatch)
    stale = dict(_dune_row(tmp_path), renamed_file=None)
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        m.rename_file(stale, db)
    row = _dune_row(tmp_path)
    assert (row["renamed_file"], placed.read_bytes(), m.logger.messages["error"]) == (str(placed), b"poster", [])


def test_a_moved_poster_whose_staged_path_was_cleared_follows_a_renamed_folder(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, placed = _moved_into_asset_folders(tmp_path, monkeypatch)
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.set_renamed_file(1, None)
    m.run()
    row = _dune_row(tmp_path)
    assert (row["renamed_file"], placed.read_bytes(), m.logger.messages["error"]) == (str(placed), b"poster", [])
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("Dune (2021) [renamed]",))
    m.run()
    landed = placed.parent.parent / "Dune (2021) [renamed]" / "poster.jpg"
    assert (landed.read_bytes(), placed.parent.exists()) == (b"poster", False)


def test_a_moved_poster_deleted_in_the_poster_list_is_not_adopted(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger
    from tests.test_posters_queries import _client

    m, placed = _moved_into_asset_folders(tmp_path, monkeypatch)
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        src = str(tmp_path / "src" / "Dune (2021) {tmdb-438631}.jpg")
        poster = db.poster.execute_query("SELECT id FROM poster_cache WHERE file=?", (src,), fetch_one=True)
        body = _client(db).delete(f"/api/posters/{poster['id']}").json()
    m.run()
    row = _dune_row(tmp_path)
    assert (body["data"]["media_unmatched"], row["renamed_file"], placed.read_bytes()) == (1, "", b"poster")


def test_a_moved_poster_whose_folder_is_renamed_leaves_no_old_folder(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, placed = _moved_into_asset_folders(tmp_path, monkeypatch)
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("Dune (2021) [renamed]",))
    m.run()
    landed = placed.parent.parent / "Dune (2021) [renamed]" / "poster.jpg"
    assert (landed.read_bytes(), placed.parent.exists()) == (b"poster", False)


@pytest.mark.parametrize("action", ["copy", "hardlink", "move"])
def test_a_symlinked_poster_becomes_a_file_once_the_action_is_not_symlink(tmp_path, monkeypatch, action):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "symlink"
    m.run()
    placed = posters / "Dune (2021).jpg"
    src = tmp_path / "src" / "Dune (2021) {tmdb-438631}.jpg"
    assert placed.is_symlink()
    m.config.action_type = action
    m.run()
    assert (placed.is_symlink(), placed.read_bytes(), src.exists()) == (False, b"poster", action != "move")
    assert (src.exists() and os.path.samefile(placed, src)) == (action == "hardlink")
    before = os.lstat(placed)
    m.run()
    after = os.lstat(placed)
    assert (after.st_ino, after.st_ctime_ns) == (before.st_ino, before.st_ctime_ns)
    assert (m.logger.messages["warning"], m.logger.messages["error"]) == ([], [])


def test_a_poster_whose_source_is_a_link_is_moved_in_as_a_file(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    src = tmp_path / "src" / "Dune (2021) {tmdb-438631}.jpg"
    target = tmp_path / "elsewhere.jpg"
    os.replace(src, target)
    os.symlink(target, src)
    m.config.action_type = "move"
    m.run()
    placed = posters / "Dune (2021).jpg"
    assert (placed.is_symlink(), placed.read_bytes()) == (False, b"poster")
    assert (os.path.lexists(src), target.read_bytes(), m.logger.messages["error"]) == (False, b"poster", [])


def test_a_symlinked_poster_whose_folder_is_renamed_leaves_no_old_link(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "symlink"
    m.run()
    placed = posters / "Dune (2021).jpg"
    assert placed.is_symlink()
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("Dune (2021) [renamed]",))
    m.run()
    landed = posters / "Dune (2021) [renamed].jpg"
    src = tmp_path / "src" / "Dune (2021) {tmdb-438631}.jpg"
    assert (landed.is_symlink(), os.path.lexists(placed), src.read_bytes()) == (True, False, b"poster")
    assert m.logger.messages["warning"] == []


def test_a_dry_run_keeps_a_picked_and_moved_poster_for_the_real_run(tmp_path, monkeypatch):
    m, _picked, placed, _reply = _pick_dune_poster(tmp_path, monkeypatch, "move")
    landed = _new_poster_folder(m, tmp_path)
    m.config.dry_run = True
    m.run()
    assert (placed.exists(), landed.exists(), _dune_row(tmp_path)["renamed_file"]) == (True, False, str(placed))
    m.config.dry_run = False
    m.run()
    assert (landed.read_bytes(), placed.exists(), m.logger.messages["error"]) == (b"new poster", False, [])


def test_a_dry_run_lists_a_moved_poster_the_real_run_will_carry(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "move"
    m.run()
    placed = posters / "Dune (2021).jpg"
    landed = _new_poster_folder(m, tmp_path)
    m.config.dry_run = True
    m.logger.messages["info"].clear()
    m.run()
    listed = "\tDune (2021).jpg -not-renamed-> Dune (2021).jpg" in m.logger.messages["info"]
    assert (listed, landed.exists(), _dune_row(tmp_path)["renamed_file"]) == (True, False, str(placed))
    m.config.dry_run = False
    m.run()
    assert (landed.read_bytes(), placed.exists(), m.logger.messages["error"]) == (b"poster", False, [])


def test_a_first_dry_run_records_where_posters_would_go_for_its_border_and_plex_steps(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.dry_run = True
    m.run()
    would = posters / "Dune (2021).jpg"
    assert (_dune_row(tmp_path)["renamed_file"], would.exists()) == (str(would), False)


def test_a_dry_run_after_a_folder_rename_leaves_the_old_folder_for_the_real_run_to_clear(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.asset_folders = True
    m.run()
    old = posters / "Dune (2021)" / "poster.jpg"
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("Dune (2021) [renamed]",))
    m.config.dry_run = True
    m.run()
    assert _dune_row(tmp_path)["renamed_file"] == str(old)
    m.config.dry_run = False
    m.run()
    landed = posters / "Dune (2021) [renamed]" / "poster.jpg"
    assert (landed.read_bytes(), old.parent.exists()) == (b"poster", False)


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_move_from_a_read_only_source_places_both_and_warns_once_per_module(tmp_path, monkeypatch):
    m, _sent, posters, logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "move"
    m.full_config.asset_renamerr.action_type = "move"
    src = tmp_path / "src"
    src.chmod(0o555)
    try:
        m.run()
        first_run = list(m.logger.messages["warning"])
        m.run()
    finally:
        src.chmod(0o755)
    assert first_run == [
        f"Moved a file but could not delete its source {src}/Dune (2021) {{tmdb-438631}}.jpg: "
        f"Permission denied. {_KEPT_HINT} 1 poster(s) were placed with their source kept this way.",
        f"Moved a file but could not delete its source {src}/Dune (2021) {{tmdb-438631}} - Logo.png: "
        f"Permission denied. {_KEPT_HINT} 1 asset(s) were placed with their source kept this way.",
    ]
    assert m.logger.messages["warning"] == first_run, "the next run must not move them again"
    assert m.logger.messages["error"] == []
    assert [p.read_bytes() for p in (posters / "Dune (2021).jpg", logos / "Dune (2021)_logo.png")] == [
        b"poster",
        b"logo",
    ]
    assert sorted(os.listdir(src)) == [
        "Dune (2021) {tmdb-438631} - Logo.png",
        "Dune (2021) {tmdb-438631}.jpg",
    ]


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_webhook_move_from_a_read_only_source_is_renamed_and_warned_once(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.action_type = "move"
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        dune = db.media.get_by_id(1)
    src = tmp_path / "src"
    src.chmod(0o555)
    try:
        result = m.run_poster_rename_adhoc([dune])
    finally:
        src.chmod(0o755)
    assert (result["success"], result["stats"]["renamed_items"]) == (True, 1)
    assert m.logger.messages["warning"] == [
        f"Moved a file but could not delete its source {src}/Dune (2021) {{tmdb-438631}}.jpg: "
        f"Permission denied. {_KEPT_HINT} 1 poster(s) were placed with their source kept this way."
    ]
    assert (posters / "Dune (2021).jpg").read_bytes() == b"poster"


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_single_poster_moved_from_a_read_only_folder_is_placed_and_warns_at_once(tmp_path):
    from tests.conftest import StubLogger

    picks, posters = tmp_path / "picks", tmp_path / "posters"
    picks.mkdir()
    posters.mkdir()
    src = picks / "Dune (2021).jpg"
    src.write_bytes(b"poster")
    dest = posters / "Dune (2021).jpg"
    m = PosterRenamerr(logger=StubLogger())
    picks.chmod(0o555)
    try:
        placed = m.process_file(str(src), str(dest), "move")
    finally:
        picks.chmod(0o755)
    assert (placed, dest.read_bytes(), src.exists()) == (True, b"poster", True)
    assert m.logger.messages["warning"] == [
        f"Moved a file but could not delete its source {src}: Permission denied. {_KEPT_HINT}"
    ]
    assert m.logger.messages["error"] == []


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_posters_written_before_a_chained_asset_refusal_are_still_reported(tmp_path, monkeypatch):
    """The root asset folder passes its check; the title folder then refuses the only logo."""
    from backend.modules.asset_renamerr import NoAssetWritten

    m, sent, posters, logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.full_config.asset_renamerr.asset_folders = True
    locked = logos / "Dune (2021)"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        with pytest.raises(NoAssetWritten):
            m.run()
    finally:
        locked.chmod(0o755)

    assert (os.listdir(posters), sent) == (["Dune (2021).jpg"], ["poster_renamerr"])


def test_chained_assets_use_asset_settings_saved_during_the_poster_pass(tmp_path, monkeypatch):
    moved = tmp_path / "logos-new"
    moved.mkdir()

    saved = []

    def _user_saves_a_new_asset_folder(live):
        saved.append(live["config"].model_copy(deep=True))
        saved[0].asset_renamerr.destination_dir = str(moved)
        live["config"] = saved[0]

    m, _sent, _posters, logos = _poster_run_with_chained_assets(
        tmp_path, monkeypatch, sync=_user_saves_a_new_asset_folder
    )
    used = {}
    monkeypatch.setattr(
        "backend.modules.poster_renamerr.NotificationManager",
        lambda cfg, log, module_name=None: SimpleNamespace(
            send_notification=lambda out: used.update({module_name: cfg})
        ),
    )
    started_with = m.full_config
    m.run()
    assert (os.listdir(logos), os.listdir(moved)) == ([], ["Dune (2021)_logo.png"])
    assert used == {"poster_renamerr": started_with, "asset_renamerr": saved[0]}


# Prints its argv's last item's kind of result; "config create" succeeds silently.
_FAKE_RCLONE = """#!/bin/sh
[ "$1" = config ] && exit 0
for last; do :; done
case "$last" in
  *broken*) echo "2026/11/15 13:00:00 ERROR : drive not found"; exit 1 ;;
  *changed*) echo "2026/11/15 13:00:00 INFO  : a.jpg: Copied (new)"
             echo "2026/11/15 13:00:00 INFO  : b.jpg: Deleted" ;;
esac
exit 0
"""


def _syncing(tmp_path, monkeypatch, *folders, rclone=_FAKE_RCLONE, sync=None):
    """The chained-asset run with sync_posters on, one gdrive folder per name, through a fake rclone."""
    from backend.util.config import GDriveListEntry

    fake = tmp_path / "rclone"
    fake.write_text(rclone)
    fake.chmod(0o755)
    monkeypatch.setenv("RCLONE_PATH", str(fake))
    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch, sync=sync)
    m.config.sync_posters = True
    m.full_config.sync_gdrive.gdrive_list = [
        GDriveListEntry(id=f"id-{n}", location=str(tmp_path / "gdrive" / n), name=n)
        for n in folders
    ]
    return m


def _run_summary(m):
    """The info lines after the last Run Summary header: what ends the log."""
    info = m.logger.messages["info"]
    [*_, header] = (i for i, line in enumerate(info) if "Run Summary" in line)
    return info[header + 1 :]


def test_the_log_ends_with_an_in_sync_drive_and_what_the_run_renamed(tmp_path, monkeypatch):
    m = _syncing(tmp_path, monkeypatch, "drive1")
    m.run()
    assert _run_summary(m) == [
        "GDrive sync      : 1/1 folders, already in sync, no changes",
        "Arr sync         : 1/1 instances synced",
        "Posters renamed  : 0 collections, 1 movie, 0 shows",
        "Asset renamerr   : 1 logo applied",
        "Result           : ✅ finished",
    ]


def test_the_summary_counts_what_the_drive_sync_changed(tmp_path, monkeypatch):
    m = _syncing(tmp_path, monkeypatch, "changed")
    m.run()
    assert _run_summary(m)[0] == "GDrive sync      : 1/1 folders, 1 copied, 1 deleted"


def test_a_failed_drive_folder_is_summed_up_and_still_fails_the_run(tmp_path, monkeypatch):
    m = _syncing(tmp_path, monkeypatch, "drive1", "broken")
    with pytest.raises(RuntimeError, match="GDrive sync failed for 1/2 folders"):
        m.run()
    assert (_run_summary(m), m.phase_failure) == (
        [
            "GDrive sync      : ❌ 1/2 folders failed",
            "Result           : ❌ failed at sync_gdrive: GDrive sync failed for 1/2 folders",
        ],
        None,
    )


def test_sync_posters_off_shows_as_off(tmp_path, monkeypatch):
    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.run()
    assert _run_summary(m)[0] == "GDrive sync      : off"


def test_a_drive_sync_with_no_runnable_rclone_shows_as_skipped(tmp_path, monkeypatch):
    m = _syncing(tmp_path, monkeypatch, "drive1")
    (tmp_path / "rclone").chmod(0o644)
    m.run()
    assert (_run_summary(m)[0], _run_summary(m)[-1]) == (
        f"GDrive sync      : ❌ skipped: RCLONE_PATH is set to '{tmp_path / 'rclone'}', "
        "but it is not an executable file.",
        "Result           : ⚠ finished, with failures above",
    )


def test_a_dry_run_says_so_first(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.dry_run = True
    m.run()
    assert (_run_summary(m)[0], os.listdir(posters)) == ("Poster renamerr ran as a dry run.", [])


def _orphan_run(tmp_path, monkeypatch, mode):
    """The chained-asset run with the orphan pass on in ``mode``, and one orphan poster in the destination."""
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.clean_orphan_assets = True
    m.full_config.poster_cleanarr.orphan_assets_mode = mode
    # The orphan pass re-reads config from disk and logs to its own file.
    monkeypatch.setattr("backend.util.config.load_config", lambda *a, **k: m.full_config)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    (posters / "Gone Movie (1999).jpg").write_bytes(b"old")
    return m, posters


def test_orphans_in_the_destination_are_summed_up(tmp_path, monkeypatch):
    m, _posters = _orphan_run(tmp_path, monkeypatch, "report")
    m.run()
    assert "Orphan cleanup   : 1 orphan found (report only)" in _run_summary(m)


def test_an_orphan_it_could_not_move_fails_the_line(tmp_path, monkeypatch):
    m, posters = _orphan_run(tmp_path, monkeypatch, "move")
    (posters / ".chub_orphan_restore").write_text("a file where the restore folder goes")
    m.run()
    assert _run_summary(m)[-3:] == [
        "Orphan cleanup   : ❌ 0 orphans moved, 1 not moved, see the cleanarr log",
        "Asset renamerr   : 1 logo applied",
        "Result           : ⚠ finished, with failures above",
    ]


def test_an_orphan_pass_that_could_not_run_says_skipped(tmp_path, monkeypatch):
    m, _posters = _orphan_run(tmp_path, monkeypatch, "bogus")
    m.run()
    assert "Orphan cleanup   : ❌ skipped, see the cleanarr log" in _run_summary(m)


def test_border_replacerr_counts_a_poster_it_could_not_border(tmp_path, monkeypatch):
    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.run_border_replacerr = True
    m.run()
    assert _run_summary(m) == [
        "GDrive sync      : off",
        "Arr sync         : 1/1 instances synced",
        "Posters renamed  : 0 collections, 1 movie, 0 shows",
        "Border replacerr : ❌ 0 changed of 1 processed, 1 failed",
        "Asset renamerr   : 1 logo applied",
        "Result           : ⚠ finished, with failures above",
    ]


def test_a_chained_module_in_its_own_dry_run_is_marked(tmp_path, monkeypatch):
    m, _sent, posters, logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.run_border_replacerr = True
    m.full_config.border_replacerr.dry_run = True
    m.full_config.asset_renamerr.dry_run = True
    m.run()
    landed = [f for _root, _dirs, files in os.walk(posters) for f in files]
    assert (landed, os.listdir(logos), _run_summary(m)[3:]) == (
        [],
        [],
        [
            "Border replacerr : [DRY RUN] 1 changed of 1 processed",
            "Asset renamerr   : [DRY RUN] 1 logo applied",
            "Result           : ✅ finished",
        ],
    )


def test_a_drive_sync_in_its_own_dry_run_is_marked(tmp_path, monkeypatch):
    m = _syncing(tmp_path, monkeypatch, "drive1")
    m.full_config.sync_gdrive.dry_run = True
    m.run()
    assert _run_summary(m)[0] == "GDrive sync      : [DRY RUN] 1/1 folders, already in sync, no changes"


def test_an_arr_instance_it_could_not_reach_fails_the_line(tmp_path, monkeypatch):
    from backend.util.config import InstanceDetail
    from backend.util.connector import Connector

    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.full_config.instances.radarr = {"radarr1": InstanceDetail(url="http://127.0.0.1:9", api="0" * 32)}
    monkeypatch.setattr("backend.util.connector.load_config", lambda *a, **k: m.full_config)
    monkeypatch.setattr("backend.modules.poster_renamerr.Connector", Connector)
    # create_arr_client returns None for an instance it cannot reach.
    monkeypatch.setattr("backend.util.connector.create_arr_client", lambda url, api, logger: None)
    m.run()
    [warned] = [w for w in m.logger.messages["warning"] if "Failed to sync radarr1: " in w]
    error = warned.split("Failed to sync radarr1: ", 1)[1]
    assert (_run_summary(m)[1], _run_summary(m)[-1]) == (
        f"Arr sync         : ❌ 0/1 instances synced, radarr1: {error}",
        "Result           : ⚠ finished, with failures above",
    )


def test_a_cancelled_run_is_summed_up_as_cancelled(tmp_path, monkeypatch):
    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m._cancel_event = threading.Event()
    m._cancel_event.set()
    m.run()
    assert _run_summary(m)[-1] == "Result           : ⏹ cancelled"


def test_a_show_counts_once_however_many_season_posters_it_got(tmp_path, monkeypatch):
    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    show = {"title": "Andor", "year": 2022, "folder": "Andor (2022)"}
    output = {"show": [show, {**show, "season_number": 1}, {**show, "season_number": 2}]}
    assert m._rename_counts(output) == {"collection": 0, "movie": 0, "show": 1}


def test_a_plex_upload_that_did_not_run_says_why(tmp_path, monkeypatch):
    m, _sent, _posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    m.config.apply_method = "plex"
    m.run()
    [upload] = [line for line in _run_summary(m) if line.startswith("Plex upload")]
    assert upload == (
        "Plex upload      : ❌ 0 uploaded, 0 failed (No Plex instances enabled for poster upload)"
    )


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_failure_before_any_step_names_no_step(tmp_path, monkeypatch):
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    posters.chmod(0o555)
    try:
        with pytest.raises(PermissionError) as raised:
            m.run()
    finally:
        posters.chmod(0o755)
    assert _run_summary(m) == [f"Result           : ❌ failed: {raised.value}"]


def test_a_keyboard_interrupt_is_summed_up_as_stopped(tmp_path, monkeypatch):
    def _interrupt(_live):
        raise KeyboardInterrupt

    m = _syncing(tmp_path, monkeypatch, "drive1", sync=_interrupt)
    m.run()
    assert _run_summary(m)[-1] == "Result           : ⏹ stopped by keyboard interrupt"


def test_a_fault_in_the_summary_never_replaces_the_runs_own_error(tmp_path, monkeypatch):
    m = _syncing(tmp_path, monkeypatch, "broken")

    def _broken(*_a):
        raise ValueError("summary bug")

    monkeypatch.setattr("backend.util.run_summary.result_text", _broken)
    with pytest.raises(RuntimeError, match="GDrive sync failed"):
        m.run()
    assert m.logger.messages["warning"][-1] == "Could not log the run summary: summary bug"


def test_title_match_reason_skips_a_poster_with_unreadable_alternate_titles():
    poster = {"season_number": None, "normalized_title": "other", "normalized_alternate_titles": "matrix"}
    reason = PosterRenamerr._title_match_reason(poster, {"season_number": None}, {"matrix"}, [])
    assert reason == ""


def _add_dune(tmp_path, instance, folder):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.upsert(
            {
                "title": "Dune",
                "normalized_title": "dune",
                "alternate_titles": "[]",
                "year": 2021,
                "tmdb_id": 438631,
                "folder": folder,
                "status": "released",
                "has_content": 1,
            },
            "movie",
            "radarr",
            instance,
        )


def _shared_by_instances(tmp_path, monkeypatch, *folders):
    """Move run: radarr1's Dune plus one per ``folders``, all matching one poster."""
    m, _sent, posters, _logos = _poster_run_with_chained_assets(tmp_path, monkeypatch)
    for n, folder in enumerate(folders, 2):
        _add_dune(tmp_path, f"radarr{n}", folder)
    m.config.instances = [f"radarr{n}" for n in range(1, len(folders) + 2)]
    m.config.action_type = "move"
    return m, posters, tmp_path / "src" / "Dune (2021) {tmdb-438631}.jpg"


def _placed(posters):
    return sorted(
        (str(p.relative_to(posters)), p.read_bytes())
        for p in posters.rglob("*")
        if p.is_file()
    )


@pytest.mark.parametrize(
    "folders, names",
    [
        (["Dune 4K (2021)"], ["Dune (2021).jpg", "Dune 4K (2021).jpg"]),
        (["Dune (2021)"], ["Dune (2021).jpg"]),
        (["Dune 4K (2021)", "Dune (2021)"], ["Dune (2021).jpg", "Dune 4K (2021).jpg"]),
    ],
    ids=["two-folders", "one-folder", "three-rows-two-folders"],
)
def test_a_moved_poster_instances_share_reaches_each_folder(
    tmp_path, monkeypatch, folders, names
):
    m, posters, src = _shared_by_instances(tmp_path, monkeypatch, *folders)
    m.run()
    each = [(name, b"poster") for name in names]
    assert (_placed(posters), src.exists(), m.logger.messages["warning"]) == (
        each,
        False,
        [],
    )
    m.run()
    assert (
        _placed(posters),
        m.logger.messages["warning"],
        m.logger.messages["error"],
    ) == (each, [], [])


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_shared_poster_that_cannot_reach_one_instance_keeps_its_source(
    tmp_path, monkeypatch
):
    m, posters, src = _shared_by_instances(tmp_path, monkeypatch, "Dune 4K (2021)")
    m.config.asset_folders = True
    blocked = posters / "Dune (2021)"
    blocked.mkdir()
    blocked.chmod(0o555)
    try:
        m.run()
    finally:
        blocked.chmod(0o755)
    other = ("Dune 4K (2021)/poster.jpg", b"poster")
    assert (_placed(posters), src.exists()) == ([other], True)
    m.run()
    both = [("Dune (2021)/poster.jpg", b"poster"), other]
    assert (_placed(posters), src.exists()) == (both, False)


def _added_later(tmp_path, monkeypatch, folder="Dune 4K (2021)"):
    """radarr1's Dune moved its poster; radarr2 then adds Dune in ``folder``."""
    m, posters, src = _shared_by_instances(tmp_path, monkeypatch)
    m.run()
    _add_dune(tmp_path, "radarr2", folder)
    m.config.instances = ["radarr1", "radarr2"]
    return m, posters, src


def test_a_moved_poster_reaches_an_instance_that_adds_the_movie_later(
    tmp_path, monkeypatch
):
    m, posters, src = _added_later(tmp_path, monkeypatch)
    m.run()
    each = [("Dune (2021).jpg", b"poster"), ("Dune 4K (2021).jpg", b"poster")]
    assert (_placed(posters), src.exists(), m.logger.messages["warning"]) == (
        each,
        False,
        [],
    )
    m.run()
    assert (
        _placed(posters),
        m.logger.messages["warning"],
        m.logger.messages["error"],
    ) == (each, [], [])


def test_an_adopted_poster_follows_its_folder_rename(tmp_path, monkeypatch):
    m, posters, _src = _added_later(tmp_path, monkeypatch)
    m.run()
    _add_dune(tmp_path, "radarr2", "Dune UHD (2021)")
    m.run()
    each = [("Dune (2021).jpg", b"poster"), ("Dune UHD (2021).jpg", b"poster")]
    assert (_placed(posters), m.logger.messages["error"]) == (each, [])


def test_a_picked_poster_is_not_replaced_by_a_siblings(tmp_path, monkeypatch):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, posters, _src = _added_later(tmp_path, monkeypatch)
    picked = tmp_path / "picked.jpg"
    picked.write_bytes(b"picked")
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        row = db.media.get_by_instance("radarr2")[0]
        db.media.update(
            asset_type="movie",
            title="Dune",
            year=2021,
            instance_name="radarr2",
            matched_value=True,
            original_file=str(picked),
            id=row["id"],
        )
        db.media.set_user_confirmed(row["id"], True)
    m.run()
    each = [("Dune (2021).jpg", b"poster"), ("Dune 4K (2021).jpg", b"picked")]
    assert _placed(posters) == each


def test_a_poster_adopted_as_its_sibling_is_renamed_reaches_both(tmp_path, monkeypatch):
    m, posters, _src = _added_later(tmp_path, monkeypatch)
    _add_dune(tmp_path, "radarr1", "Dune Part One (2021)")
    m.run()
    each = [("Dune 4K (2021).jpg", b"poster"), ("Dune Part One (2021).jpg", b"poster")]
    assert (_placed(posters), m.logger.messages["warning"]) == (each, [])


def test_a_sibling_whose_row_lost_its_staged_path_keeps_its_poster(
    tmp_path, monkeypatch
):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, posters, _src = _added_later(tmp_path, monkeypatch)
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.set_renamed_file(db.media.get_by_instance("radarr1")[0]["id"], None)
    m.run()
    own = [("Dune (2021).jpg", b"poster")]
    assert (_placed(posters), m.logger.messages["warning"]) == (own, [])
    m.run()
    each = [*own, ("Dune 4K (2021).jpg", b"poster")]
    assert (_placed(posters), m.logger.messages["warning"]) == (each, [])


def test_an_unmatched_poster_whose_source_is_on_disk_is_not_replaced(
    tmp_path, monkeypatch
):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, posters, _src = _added_later(tmp_path, monkeypatch)
    own_source = tmp_path / "own.jpg"
    own_source.write_bytes(b"own")
    staged = posters / "Dune 4K (2021).jpg"
    staged.write_bytes(b"own")
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.update(
            asset_type="movie",
            title="Dune",
            year=2021,
            instance_name="radarr2",
            original_file=str(own_source),
            renamed_file=str(staged),
            id=db.media.get_by_instance("radarr2")[0]["id"],
        )
    m.run()
    each = [("Dune (2021).jpg", b"poster"), ("Dune 4K (2021).jpg", b"own")]
    assert _placed(posters) == each


def _pick_dune(tmp_path, instance):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    picked = tmp_path / "picked.jpg"
    picked.write_bytes(b"picked")
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        row_id = db.media.get_by_instance(instance)[0]["id"]
        db.media.update(
            asset_type="movie",
            title="Dune",
            year=2021,
            instance_name=instance,
            matched_value=True,
            original_file=str(picked),
            id=row_id,
        )
        db.media.set_user_confirmed(row_id, True)
    return picked


def test_an_approved_poster_is_adopted_by_an_instance_added_later(
    tmp_path, monkeypatch
):
    from backend.util.database import ChubDB
    from tests.conftest import StubLogger

    m, posters, src = _shared_by_instances(tmp_path, monkeypatch)
    m.run()
    with ChubDB(StubLogger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.approve_match(db.media.get_by_instance("radarr1")[0]["id"])
    _add_dune(tmp_path, "radarr2", "Dune 4K (2021)")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    each = [("Dune (2021).jpg", b"poster"), ("Dune 4K (2021).jpg", b"poster")]
    assert (_placed(posters), src.exists()) == (each, False)


def test_a_moved_pick_keeps_its_poster_beside_a_sibling(tmp_path, monkeypatch):
    m, posters, _src = _added_later(tmp_path, monkeypatch)
    picked = _pick_dune(tmp_path, "radarr2")
    m.run()
    m.run()
    each = [("Dune (2021).jpg", b"poster"), ("Dune 4K (2021).jpg", b"picked")]
    assert (_placed(posters), picked.exists()) == (each, False)

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

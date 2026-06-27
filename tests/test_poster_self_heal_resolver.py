"""Resolver scenarios for poster_self_heal — every branch of resolve_poster.

Each poster is matched to a fake live media row and (where it has a tmdb id) a
fake TMDB get_details, so the test exercises the real matching + filename-rebuild
logic without a DB or network. Mirrors the exhaustive manual dry-run.
"""

import pytest

from backend.util.normalization import normalize_titles as N
from backend.util.poster_self_heal.resolver import index_media, resolve_poster


class FakeTMDB:
    enabled = True

    def __init__(self, details):
        self._d = details

    def get_details(self, tmdb_id, mt):
        return self._d.get(tmdb_id, {"verified": True, "title": None, "year": None})


class Cfg:
    def __init__(self, backfill_ids=True):
        self.backfill_ids = backfill_ids


def media(asset_type, title, year, tmdb=None, tvdb=None, imdb=None):
    return {
        "matched": 1,
        "asset_type": asset_type,
        "title": title,
        "normalized_title": N(title),
        "year": year,
        "tmdb_id": tmdb,
        "tvdb_id": tvdb,
        "imdb_id": imdb,
    }


def poster(
    fname,
    asset_type,
    title,
    year,
    tmdb=None,
    tvdb=None,
    imdb=None,
    season=None,
    image="poster",
):
    return {
        "file": "/cl2k/" + fname,
        "asset_type": asset_type,
        "title": title,
        "normalized_title": N(title),
        "year": year,
        "tmdb_id": tmdb,
        "tvdb_id": tvdb,
        "imdb_id": imdb,
        "season_number": season,
        "image_type": image,
    }


def _resolve(p, rows, details, cfg=None):
    return resolve_poster(
        p, index_media(rows), "FOLDER", FakeTMDB(details), cfg or Cfg()
    )


def test_backfill_by_title_year():
    r = _resolve(
        poster("Some Movie (2010).jpg", "movie", "Some Movie", 2010),
        [media("movie", "Some Movie", 2010, tmdb=111, imdb="tt1")],
        {111: {"verified": True, "title": "Some Movie", "year": 2010}},
    )
    assert r["proposed_filename"] == "Some Movie (2010) {tmdb-111} {imdb-tt1}.jpg"
    assert "backfill" in r["drift_type"] and "imdb" in r["drift_type"]
    assert r["status"] == "proposed" and r["confidence"] == pytest.approx(0.9)


def test_dead_tmdb_id_bridged_by_tvdb():
    r = _resolve(
        poster(
            "The Savant (2026) {tmdb-990} {tvdb-432966}.jpg",
            "show",
            "The Savant",
            2026,
            tmdb=990,
            tvdb=432966,
        ),
        [media("show", "The Savant", 2026, tmdb=555, tvdb=432966)],
        {
            990: {"verified": False, "title": None, "year": None},
            555: {"verified": True, "title": "The Savant", "year": 2026},
        },
    )
    assert r["proposed_filename"] == "The Savant (2026) {tmdb-555} {tvdb-432966}.jpg"
    assert r["drift_type"] == "tmdb"
    assert r["confidence"] == pytest.approx(0.95)  # id match


def test_title_drift():
    r = _resolve(
        poster(
            "Working Title (2024) {tmdb-100}.jpg",
            "movie",
            "Working Title",
            2024,
            tmdb=100,
        ),
        [media("movie", "Working Title", 2024, tmdb=100)],
        {100: {"verified": True, "title": "Final Title", "year": 2024}},
    )
    assert r["proposed_filename"] == "Final Title (2024) {tmdb-100}.jpg"
    assert r["drift_type"] == "title"


def test_year_drift():
    r = _resolve(
        poster("Movie X (2023) {tmdb-200}.jpg", "movie", "Movie X", 2023, tmdb=200),
        [media("movie", "Movie X", 2024, tmdb=200)],
        {200: {"verified": True, "title": "Movie X", "year": 2024}},
    )
    assert r["proposed_filename"] == "Movie X (2024) {tmdb-200}.jpg"
    assert r["drift_type"] == "year"


def test_stale_tvdb():
    r = _resolve(
        poster(
            "Show Y (2020) {tmdb-300} {tvdb-111}.jpg",
            "show",
            "Show Y",
            2020,
            tmdb=300,
            tvdb=111,
        ),
        [media("show", "Show Y", 2020, tmdb=300, tvdb=222)],
        {300: {"verified": True, "title": "Show Y", "year": 2020}},
    )
    assert r["proposed_filename"] == "Show Y (2020) {tmdb-300} {tvdb-222}.jpg"
    assert r["drift_type"] == "tvdb"


def test_stale_imdb():
    r = _resolve(
        poster(
            "Movie Z (2019) {tmdb-400} {imdb-tt000}.jpg",
            "movie",
            "Movie Z",
            2019,
            tmdb=400,
            imdb="tt000",
        ),
        [media("movie", "Movie Z", 2019, tmdb=400, imdb="tt999")],
        {400: {"verified": True, "title": "Movie Z", "year": 2019}},
    )
    assert r["proposed_filename"] == "Movie Z (2019) {tmdb-400} {imdb-tt999}.jpg"
    assert r["drift_type"] == "imdb"


def test_combined_backfill_imdb_year():
    r = _resolve(
        poster(
            "The Savant (2025) {tvdb-432966}.jpg",
            "show",
            "The Savant",
            2025,
            tvdb=432966,
        ),
        [media("show", "The Savant", 2026, tmdb=909, tvdb=432966, imdb="tt111")],
        {909: {"verified": True, "title": "The Savant", "year": 2026}},
    )
    assert (
        r["proposed_filename"]
        == "The Savant (2026) {tmdb-909} {tvdb-432966} {imdb-tt111}.jpg"
    )
    for part in ("backfill", "imdb", "year"):
        assert part in r["drift_type"]


def test_ambiguous_is_pending_with_no_rename():
    p = poster("Greatest Hits (2024).jpg", "movie", "Greatest Hits", 2024)
    r = _resolve(
        p,
        [
            media("movie", "Greatest Hits", 2024, tmdb=1),
            media("movie", "Greatest Hits", 2024, tmdb=2),
        ],
        {},
    )
    assert r["status"] == "pending" and r["drift_type"] == "ambiguous"
    assert r["proposed_filename"] == r["current_filename"]


def test_no_library_match_is_noop():
    assert (
        _resolve(
            poster("Unknown Film (2099).jpg", "movie", "Unknown Film", 2099),
            [media("movie", "Some Movie", 2010, tmdb=111)],
            {},
        )
        is None
    )


def test_already_canonical_is_noop():
    assert (
        _resolve(
            poster(
                "Perfect (2021) {tmdb-500} {tvdb-600} {imdb-tt5}.jpg",
                "movie",
                "Perfect",
                2021,
                tmdb=500,
                tvdb=600,
                imdb="tt5",
            ),
            [media("movie", "Perfect", 2021, tmdb=500, tvdb=600, imdb="tt5")],
            {500: {"verified": True, "title": "Perfect", "year": 2021}},
        )
        is None
    )


def test_transient_tmdb_failure_is_noop():
    assert (
        _resolve(
            poster(
                "Net Down (2022) {tmdb-700}.jpg", "movie", "Net Down", 2022, tmdb=700
            ),
            [media("movie", "Net Down", 2022, tmdb=700)],
            {700: None},
        )
        is None
    )


def test_backfill_disabled_skips_idless():
    assert (
        _resolve(
            poster("Some Movie (2010).jpg", "movie", "Some Movie", 2010),
            [media("movie", "Some Movie", 2010, tmdb=111)],
            {111: {"verified": True, "title": "Some Movie", "year": 2010}},
            Cfg(backfill_ids=False),
        )
        is None
    )


def test_season_poster_heals_title_keeping_tag():
    # A season poster heals the show's title/id while KEEPING its ` - Season NN`
    # tag (the regression was dropping it).
    r = _resolve(
        poster(
            "Big Sho (2018) {tmdb-800} - Season 02.jpg",
            "show",
            "Big Sho",
            2018,
            tmdb=800,
            season=2,
        ),
        [media("show", "Big Show", 2018, tmdb=800)],
        {800: {"verified": True, "title": "Big Show", "year": 2018}},
    )
    assert r["proposed_filename"] == "Big Show (2018) {tmdb-800} - Season 02.jpg"
    assert r["drift_type"] == "title"


def test_specials_poster_heals_title_keeping_tag():
    # Season 0 = Specials — must keep the ` - Specials` tag (0 is a real season,
    # not 'absent', so _season_int preserves it).
    r = _resolve(
        poster(
            "Big Sho (2018) {tmdb-800} - Specials.jpg",
            "show",
            "Big Sho",
            2018,
            tmdb=800,
            season=0,
        ),
        [media("show", "Big Show", 2018, tmdb=800)],
        {800: {"verified": True, "title": "Big Show", "year": 2018}},
    )
    assert r["proposed_filename"] == "Big Show (2018) {tmdb-800} - Specials.jpg"
    assert r["drift_type"] == "title"


def test_logo_asset_keeps_suffix():
    r = _resolve(
        poster(
            "Old Name (2019) {tmdb-410} - Logo.jpg",
            "show",
            "Old Name",
            2019,
            tmdb=410,
            image="logo",
        ),
        [media("show", "New Name", 2019, tmdb=410)],
        {410: {"verified": True, "title": "New Name", "year": 2019}},
    )
    assert r["proposed_filename"] == "New Name (2019) {tmdb-410} - Logo.jpg"

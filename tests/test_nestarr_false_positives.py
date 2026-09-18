"""Regression tests for nestarr / unmatched-assets false positives.

Covers three fixes:
  1. _find_plex_match year matching uses ±1 tolerance and tolerates a missing
     year on either side (was exact string equality → false "Not in ARR").
  2. _parse_plex_guids extracts MusicBrainz ids (mbid).
  3. _NestScanner._normalize_fs_name compares folder basenames NFC-normalized
     and whitespace-trimmed (was byte-for-byte → false "Stray Folder").
"""

import json
import unicodedata

from backend.modules.nestarr import _NestScanner
from backend.util.connector import Connector


def _connector():
    """Build a Connector without running __init__ (avoids config/db deps).

    The matching helpers only touch self.logger, which we leave as None.
    """
    conn = Connector.__new__(Connector)
    conn.logger = None
    return conn


def _plex_item(title, year, *, guids=None, season=None, plex_id=1):
    return {
        "id": plex_id,
        "title": title,
        "year": year,
        "season_number": season,
        "guids": json.dumps(guids or {}),
    }


# --- _clean_year ---------------------------------------------------------


def test_clean_year_parses_and_blanks():
    assert Connector._clean_year(2013) == 2013
    assert Connector._clean_year("2013") == 2013
    assert Connector._clean_year(None) is None
    assert Connector._clean_year("") is None
    assert Connector._clean_year("None") is None
    assert Connector._clean_year(0) is None
    assert Connector._clean_year("garbage") is None


# --- _find_plex_match year tolerance ------------------------------------


def test_year_off_by_one_still_matches_on_title():
    conn = _connector()
    media = {"title": "Some Show", "year": 2013, "season_number": None}
    plex = [_plex_item("Some Show", 2012)]
    assert conn._find_plex_match(media, plex) == 1


def test_missing_arr_year_matches_yeared_plex():
    conn = _connector()
    # e.g. "House of Anubis" tracked in ARR without a year vs Plex (2011).
    media = {"title": "House of Anubis", "year": None, "season_number": None}
    plex = [_plex_item("House of Anubis", 2011)]
    assert conn._find_plex_match(media, plex) == 1


def test_year_off_by_two_does_not_match_on_title():
    conn = _connector()
    media = {"title": "Some Show", "year": 2013, "season_number": None}
    plex = [_plex_item("Some Show", 2010)]
    assert conn._find_plex_match(media, plex) is None


def test_different_title_does_not_match_even_with_same_year():
    conn = _connector()
    media = {"title": "Totally Different", "year": 2013, "season_number": None}
    plex = [_plex_item("Some Show", 2013)]
    assert conn._find_plex_match(media, plex) is None


def test_id_match_wins_regardless_of_year():
    conn = _connector()
    media = {
        "title": "Renamed Differently",
        "year": 1999,
        "season_number": None,
        "tvdb_id": "269586",
    }
    plex = [_plex_item("Brooklyn Nine-Nine", 2013, guids={"tvdb": "269586"})]
    assert conn._find_plex_match(media, plex) == 1


# --- _parse_plex_guids mbid ---------------------------------------------


def test_parse_guids_dict_includes_mbid():
    conn = _connector()
    guids = conn._parse_plex_guids(json.dumps({"mbid": "abc-123", "tmdb": "5"}))
    assert guids.get("mbid") == "abc-123"
    assert guids.get("tmdb") == "5"


def test_parse_guids_uri_mbid():
    conn = _connector()
    guids = conn._parse_plex_guids(json.dumps(["mbid://abc-123"]))
    assert guids.get("mbid") == "abc-123"


# --- _normalize_fs_name (stray folder) ----------------------------------


def test_normalize_fs_name_nfc_equivalence():
    # "Pokémon" with a combining accent (NFD) vs precomposed (NFC) — the kind
    # of mismatch os.listdir vs ARR-API produces. Both must normalize equal.
    nfd = unicodedata.normalize("NFD", "Pokémon (1997)")
    nfc = unicodedata.normalize("NFC", "Pokémon (1997)")
    assert nfd != nfc  # genuinely different byte sequences
    assert _NestScanner._normalize_fs_name(nfd) == _NestScanner._normalize_fs_name(
        nfc
    )


def test_normalize_fs_name_trims_whitespace():
    assert _NestScanner._normalize_fs_name("Movie (2020) ") == "Movie (2020)"

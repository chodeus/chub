"""Tests for backend/util/helper.py — match, extraction, table, variant logic."""

import os


from backend.util.helper import (
    compare_strings,
    create_bar,
    create_table,
    dict_diff,
    extract_ids,
    extract_year,
    generate_title_variants,
    get_config_dir,
    get_log_dir,
    get_prefix,
    is_match,
    progress,
)


# --- extract_year ---


def test_extract_year_matches_parenthesized():
    assert extract_year("Movie (1999)") == 1999


def test_extract_year_returns_none_when_absent():
    assert extract_year("Movie") is None


def test_extract_year_ignores_collection_marker():
    # year_regex has negative lookahead for "Collection"
    assert extract_year("Movie (2020) Collection extras") is None


# --- extract_ids ---


def test_extract_ids_tmdb():
    tmdb, tvdb, imdb = extract_ids("Movie {tmdb-12345}")
    assert tmdb == 12345
    assert tvdb is None
    assert imdb is None


def test_extract_ids_tvdb_variants():
    tmdb, tvdb, imdb = extract_ids("Show {tvdb 99}")
    assert tvdb == 99


def test_extract_ids_imdb_tt_prefix():
    tmdb, tvdb, imdb = extract_ids("Movie {imdb-tt1234567}")
    assert imdb == "tt1234567"


def test_extract_ids_returns_none_when_absent():
    assert extract_ids("Just a title") == (None, None, None)


# --- compare_strings ---


def test_compare_strings_ignores_punctuation_and_case():
    assert compare_strings("Mr & Mrs Smith", "Mr&Mrs.Smith") is True
    assert compare_strings("the matrix!", "The Matrix") is True


def test_compare_strings_distinguishes_different():
    assert compare_strings("Inception", "Interstellar") is False


# --- generate_title_variants ---


def test_generate_title_variants_drops_leading_article():
    variants = generate_title_variants("The Matrix")
    assert "Matrix" in variants["alternate_titles"]


def test_generate_title_variants_adds_collection_when_missing():
    variants = generate_title_variants("Star Wars")
    assert "Star Wars Collection" in variants["alternate_titles"]


def test_generate_title_variants_does_not_add_collection_if_present():
    variants = generate_title_variants("Star Wars Collection")
    # Should not add another "... Collection Collection"
    assert "Star Wars Collection Collection" not in variants["alternate_titles"]


def test_generate_title_variants_alignment():
    variants = generate_title_variants("The Matrix")
    assert len(variants["alternate_titles"]) == len(
        variants["normalized_alternate_titles"]
    )


# --- get_prefix ---


def test_get_prefix_skips_common_words():
    # "The" is a common word, skipped
    assert get_prefix("The Matrix") == "mat"


def test_get_prefix_default_length_three():
    assert len(get_prefix("Inception")) == 3


def test_get_prefix_fallback_when_all_common():
    # all words are common -> fall back to full text
    result = get_prefix("The And Or")
    assert result  # not empty


# --- is_match ---


def test_is_match_id_tmdb():
    asset = {"tmdb_id": "123"}
    media = {"tmdb_id": "123"}
    matched, reason = is_match(asset, media)
    assert matched
    assert "tmdb_id" in reason


def test_is_match_id_mismatch_blocks_title_fallback():
    """When both have IDs and they don't match, return False (no title fallback)."""
    asset = {"tmdb_id": "1", "title": "Same Title", "year": 2020}
    media = {"tmdb_id": "2", "title": "Same Title", "year": 2020}
    matched, _ = is_match(asset, media)
    assert matched is False


def test_is_match_title_match_no_ids():
    asset = {"title": "Inception", "year": 2010}
    media = {"title": "Inception", "year": 2010}
    matched, reason = is_match(asset, media)
    assert matched
    assert reason  # has a diagnostic string


def test_is_match_year_mismatch_blocks_title_match():
    asset = {"title": "Inception", "year": 2010}
    media = {"title": "Inception", "year": 1999}
    matched, _ = is_match(asset, media)
    assert matched is False


def test_is_match_normalized_title_match():
    asset = {"normalized_title": "inception", "year": 2010}
    media = {"normalized_title": "inception", "year": 2010}
    matched, _ = is_match(asset, media)
    assert matched


def test_is_match_no_match_returns_empty_reason():
    matched, reason = is_match(
        {"title": "A", "year": 1900}, {"title": "B", "year": 2000}
    )
    assert matched is False
    assert reason == ""


def test_is_match_imdb_id_match():
    asset = {"imdb_id": "tt1234567"}
    media = {"imdb_id": "tt1234567"}
    matched, reason = is_match(asset, media)
    assert matched
    assert "imdb_id" in reason


def test_is_match_imdb_invalid_format_ignored():
    """imdb_id must start with 'tt' to count as a valid ID."""
    asset = {"imdb_id": "1234567", "title": "X", "year": 2000}  # invalid imdb
    media = {"imdb_id": "1234567", "title": "X", "year": 2000}
    matched, _ = is_match(asset, media)
    # IDs invalid -> falls through to title matching -> match by title
    assert matched is True


# --- New behavior added in 57cd537 (ID-source overlap rule) ---


def test_is_match_falls_back_to_title_when_id_sources_dont_overlap():
    """Asset has only tmdb_id, media has only tvdb_id — no shared source,
    so title/year heuristics should still run."""
    asset = {"tmdb_id": "5", "title": "Show", "year": 2020}
    media = {"tvdb_id": "9", "title": "Show", "year": 2020}
    matched, reason = is_match(asset, media)
    assert matched is True
    # Match should land on a title rule, not an ID rule
    assert "ID match" not in reason


def test_is_match_shared_id_mismatch_short_circuits_even_with_other_unique_ids():
    """Both have tmdb_id (values differ); media also has tvdb_id only.
    The shared source mismatching short-circuits to False."""
    asset = {"tmdb_id": "1", "title": "T", "year": 2020}
    media = {"tmdb_id": "2", "tvdb_id": "9", "title": "T", "year": 2020}
    matched, _ = is_match(asset, media)
    assert matched is False


def test_is_match_zero_ids_treated_as_missing():
    """ID values of 0 / "0" / "" / "None" should be ignored as invalid,
    leaving title fallback in play."""
    asset = {"tmdb_id": 0, "title": "X", "year": 2020}
    media = {"tmdb_id": "0", "title": "X", "year": 2020}
    matched, _ = is_match(asset, media)
    # No valid shared ID -> title match wins
    assert matched is True


def test_is_match_imdb_id_case_insensitive():
    """imdb_id should normalize case before comparison."""
    asset = {"imdb_id": "TT1234567"}
    media = {"imdb_id": "tt1234567"}
    matched, reason = is_match(asset, media)
    assert matched is True
    assert "imdb_id" in reason


def test_is_match_year_accepts_string_form():
    """Year stored as a string (DB JSON form) should still match."""
    asset = {"title": "Inception", "year": "2010"}
    media = {"title": "Inception", "year": 2010}
    matched, _ = is_match(asset, media)
    assert matched is True


def test_is_match_year_none_string_treated_as_missing():
    """Literal 'None' / '' should be normalized to None and skip the year check."""
    asset = {"title": "Inception", "year": "None"}
    media = {"title": "Inception", "year": ""}
    matched, _ = is_match(asset, media)
    assert matched is True  # both years None -> year check passes


def test_is_match_alternate_titles_as_json_string():
    """media.alternate_titles can arrive as a JSON-encoded string from the DB."""
    asset = {"title": "AltName", "year": 2020}
    media = {
        "title": "Canonical",
        "year": 2020,
        "alternate_titles": '["AltName", "OtherName"]',
    }
    matched, reason = is_match(asset, media)
    assert matched is True
    assert "alternate" in reason.lower()


def test_is_match_normalized_alternate_titles_as_json_string():
    asset = {"normalized_title": "altname", "year": 2020}
    media = {
        "normalized_title": "canonical",
        "year": 2020,
        "normalized_alternate_titles": '["altname"]',
    }
    matched, _ = is_match(asset, media)
    assert matched is True


def test_is_match_invalid_json_alternate_titles_handled():
    """Malformed JSON in alternate_titles must not raise."""
    asset = {"title": "X", "year": 2020}
    media = {"title": "X", "year": 2020, "alternate_titles": "not-json"}
    matched, _ = is_match(asset, media)
    # Falls back to direct title equality
    assert matched is True


def test_is_match_folder_year_annotation():
    """When media has 'folder' with (YYYY), match parses folder_title/year."""
    asset = {"title": "Inception", "year": 2010}
    media = {"folder": "/data/movies/Inception (2010)"}
    matched, _ = is_match(asset, media)
    # After processing media should have folder_title/year populated
    assert media.get("folder_title") == "Inception"
    assert media.get("folder_year") == 2010
    assert matched


# --- dict_diff ---


def test_dict_diff_detects_change():
    diffs = dict_diff({"a": 1}, {"a": 2})
    assert ("a", 1, 2) in diffs


def test_dict_diff_detects_addition():
    diffs = dict_diff({}, {"a": 1})
    assert ("a", None, 1) in diffs


def test_dict_diff_nested():
    diffs = dict_diff({"x": {"y": 1}}, {"x": {"y": 2}})
    assert any("x.y" in path for path, _, _ in diffs)


def test_dict_diff_no_change_returns_empty():
    assert dict_diff({"a": 1}, {"a": 1}) == []


def test_dict_diff_list_grow():
    diffs = dict_diff([1, 2], [1, 2, 3])
    assert any(new == 3 for _, _, new in diffs)


# --- create_table ---


def test_create_table_renders_rows():
    out = create_table([["Header"], ["Row1"]])
    assert "Header" in out
    assert "Row1" in out


def test_create_table_empty():
    assert "No data" in create_table([])


# --- create_bar ---


def test_create_bar_centers_text():
    bar = create_bar("OK")
    assert "OK" in bar
    assert len(bar.splitlines()[1]) >= 76


# --- progress ---


def test_progress_dummy_when_console_off(monkeypatch):
    monkeypatch.delenv("LOG_TO_CONSOLE", raising=False)
    result = list(progress([1, 2, 3]))
    assert result == [1, 2, 3]


# --- get_log_dir / get_config_dir ---


def test_get_log_dir_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    d = get_log_dir("modx")
    assert d.startswith(str(tmp_path))
    assert os.path.isdir(d)


def test_get_config_dir_returns_path():
    d = get_config_dir()
    assert isinstance(d, str) and d

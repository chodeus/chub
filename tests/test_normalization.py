"""Tests for backend/util/normalization.py — title/filename normalization."""

from backend.util.normalization import (
    normalize_file_names,
    normalize_titles,
    parse_asset_filename,
    remove_common_words,
    remove_tokens,
)


# --- remove_common_words ---


def test_remove_common_words_strips_articles():
    assert remove_common_words("The Matrix") == "Matrix"
    assert remove_common_words("A Few Good Men") == "Few Good Men"


def test_remove_common_words_case_insensitive():
    assert remove_common_words("THE Matrix") == "Matrix"


def test_remove_common_words_preserves_no_articles():
    assert remove_common_words("Inception") == "Inception"


def test_remove_common_words_only_strips_complete_words():
    # "The" inside a word should not be stripped
    assert "Theater" in remove_common_words("Theater")


# --- remove_tokens ---


def test_remove_tokens_strips_locale_tags():
    assert remove_tokens("The Office (US)") == "The Office "
    assert remove_tokens("The Office (UK)") == "The Office "


def test_remove_tokens_strips_dcs():
    assert "DC's" not in remove_tokens("DC's Legends of Tomorrow")


def test_remove_tokens_case_insensitive():
    # Lowercase locale tags should also strip; regression from the
    # previous case-sensitive str.replace pipeline.
    assert remove_tokens("The Office (us)") == "The Office "
    assert remove_tokens("Show (Uk)") == "Show "


# --- normalize_titles unicode + ampersand handling ---


def test_normalize_titles_ampersand_becomes_and():
    # Asset side and arr side both normalize, so "Tom & Jerry" and
    # "Tom and Jerry" should converge.
    assert normalize_titles("Tom & Jerry") == normalize_titles("Tom and Jerry")


def test_normalize_titles_strips_nbsp():
    # NBSP   must not survive into the matching key.
    nbsp = "Movie Title"
    assert normalize_titles(nbsp) == normalize_titles("Movie Title")


def test_normalize_titles_strips_zero_width():
    zwsp = "Movie​Title"
    assert normalize_titles(zwsp) == normalize_titles("Movie Title")


def test_normalize_titles_normalizes_em_dash():
    # en/em dashes get converted to ASCII hyphen, then stripped by
    # remove_special_chars; result equals the no-dash form.
    assert normalize_titles("A — B") == normalize_titles("A B")


def test_normalize_titles_strips_emoji():
    assert normalize_titles("Movie \U0001F3AC") == normalize_titles("Movie")


def test_normalize_titles_handles_decomposed_diacritic():
    # NFD form ("cafe" + combining acute) should normalize to the same
    # ASCII as the NFC form.
    nfd = "café"
    assert normalize_titles(nfd) == normalize_titles("café")


# --- parse_asset_filename unicode handling ---


def test_parse_asset_filename_strips_emoji():
    assert parse_asset_filename("Movie \U0001F3AC (2020).jpg") == "Movie"


def test_parse_asset_filename_strips_nbsp():
    out = parse_asset_filename("Show Title (2024) - Season 1.jpg")
    assert " " not in out
    assert out == "Show Title"


def test_parse_asset_filename_keeps_bare_season_in_movie_title():
    """A bare "Season <n>" in a movie title (no " - "/"_" delimiter) is part of
    the title and must survive parsing. Only a delimited " - Season N" suffix is
    a real season tag. Regression for 'Open Season 2' being mutilated to 'Open'.
    """
    assert (
        parse_asset_filename("Open Season 2 (2008) {tmdb-13690} {imdb-tt1107365}.jpg")
        == "Open Season 2"
    )
    assert (
        parse_asset_filename("Open Season 3 (2010) {tmdb-51170}.jpg") == "Open Season 3"
    )


# --- normalize_file_names ---


def test_normalize_file_names_strips_extension():
    assert "jpg" not in normalize_file_names("Movie (2020).jpg")
    assert "png" not in normalize_file_names("Movie.png")


def test_normalize_file_names_strips_id_tokens():
    out = normalize_file_names("Movie {tmdb-123} (2020).jpg")
    assert "tmdb" not in out
    assert "123" not in out


def test_normalize_file_names_strips_bracket_id_tokens():
    """57cd537 widened id_content_regex to also match [tmdb-123] style tags."""
    out = normalize_file_names("Movie [tmdb-456] (2020).jpg")
    assert "tmdb" not in out
    assert "456" not in out


def test_normalize_file_names_strips_bracket_tvdb():
    out = normalize_file_names("Show [tvdb-789].jpg")
    assert "tvdb" not in out
    assert "789" not in out


def test_normalize_file_names_strips_bracket_imdb():
    out = normalize_file_names("Movie [imdb-tt1234567].jpg")
    assert "imdb" not in out
    assert "tt1234567" not in out


def test_normalize_file_names_lowercases_and_no_spaces():
    out = normalize_file_names("The Matrix Reloaded.jpg")
    assert " " not in out
    assert out == out.lower()


def test_normalize_file_names_handles_unicode():
    out = normalize_file_names("Pokémon.jpg")
    assert "Pokémon" not in out
    # unidecode renders é as e
    assert "pok" in out


def test_normalize_file_names_handles_html_entities():
    out = normalize_file_names("Tom &amp; Jerry.jpg")
    # & is not letter/digit so removed
    assert "amp" not in out


# --- normalize_titles ---


def test_normalize_titles_strips_year():
    assert "2020" not in normalize_titles("Movie (2020)")


def test_normalize_titles_preserves_collection_keyword_after_year():
    # year_regex specifically uses negative lookahead for "Collection"
    out = normalize_titles("The Avengers Collection")
    assert "collection" in out.lower()


def test_normalize_titles_id_block_stripped():
    out = normalize_titles("Movie {imdb-tt1234567}")
    assert "imdb" not in out
    assert "tt1234567" not in out


def test_normalize_titles_returns_lowercase():
    out = normalize_titles("CAPS LOCK MOVIE")
    assert out == out.lower()


def test_parse_asset_filename_strips_idsuffix_blocks():
    """{tvdbid-..}/{tmdbid-..} blocks (with the 'id' suffix) must be stripped
    from the title, consistent with extract_ids — otherwise the id leaks into
    normalized_title and breaks matching."""
    assert parse_asset_filename("Show {tvdbid-12345} (2020).jpg") == "Show"
    assert parse_asset_filename("Movie {tmdbid 678} (2019).jpg") == "Movie"
    assert "tvdbid" not in normalize_titles("Show {tvdbid-12345} (2020)")

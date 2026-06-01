"""Tests for backend.util.plex_index.PlexMediaIndex — the shared guid-first,
type-separated lookup over plex_media_cache rows used by the poster uploader and
asset_renamerr's plex apply path."""

import json

from backend.util.plex_index import PlexMediaIndex


def _movie(plex_id, lib, *, tmdb=None, imdb=None, title="The Film", norm="thefilm"):
    guids = {}
    if tmdb:
        guids["tmdb"] = tmdb
    if imdb:
        guids["imdb"] = imdb
    return {
        "plex_id": plex_id,
        "instance_name": "plex1",
        "asset_type": "movie",
        "library_name": lib,
        "title": title,
        "normalized_title": norm,
        "season_number": None,
        "guids": guids,
    }


def _show(plex_id, lib, *, tvdb=None, season=None, title="The Show", norm="theshow"):
    guids = {}
    if tvdb:
        guids["tvdb"] = tvdb
    return {
        "plex_id": plex_id,
        "instance_name": "plex1",
        "asset_type": "show",
        "library_name": lib,
        "title": title,
        "normalized_title": norm,
        "season_number": season,
        "guids": guids,
    }


def test_movie_resolves_by_tmdb_guid_first():
    idx = PlexMediaIndex([_movie(1, "Movies", tmdb="42", imdb="tt9")])
    entries, key = idx.resolve(
        {"tmdb_id": "42", "imdb_id": "tt000", "title": "Wrong Title"},
        media_type="movie",
    )
    assert key == "TMDB"
    assert [e["plex_id"] for e in entries] == [1]


def test_movie_title_fallback_when_no_guid():
    idx = PlexMediaIndex([_movie(1, "Movies", title="The Film", norm="thefilm")])
    entries, key = idx.resolve(
        {"tmdb_id": None, "imdb_id": None, "title": "The Film"},
        media_type="movie",
    )
    assert key == "TITLE"
    assert [e["plex_id"] for e in entries] == [1]


def test_movie_in_multiple_libraries_returns_all_copies():
    # Same tmdb in an HD and a 4K library — both must be returned.
    idx = PlexMediaIndex(
        [_movie(1, "Movies", tmdb="42"), _movie(2, "Movies 4K", tmdb="42")]
    )
    entries, _ = idx.resolve({"tmdb_id": "42"}, media_type="movie")
    assert {e["library_name"] for e in entries} == {"Movies", "Movies 4K"}


def test_type_separation_movie_not_found_in_show_index():
    idx = PlexMediaIndex([_show(10, "TV", tvdb="500")])
    # A movie lookup against an index holding only a show resolves to nothing.
    entries, key = idx.resolve(
        {"tmdb_id": "42", "title": "The Show"}, media_type="movie"
    )
    assert entries == [] and key is None


def test_season_resolves_with_suffixed_key():
    idx = PlexMediaIndex([_show(10, "TV", tvdb="500", season=1)])
    entries, key = idx.resolve(
        {"tvdb_id": "500", "title": "x"}, media_type="season", season_number=1
    )
    assert key == "TVDB"
    assert [e["plex_id"] for e in entries] == [10]
    # A different season number does not match the S1 entry.
    entries2, _ = idx.resolve(
        {"tvdb_id": "500"}, media_type="season", season_number=2
    )
    assert entries2 == []


def test_show_main_entry_resolves_by_tvdb():
    idx = PlexMediaIndex([_show(10, "TV", tvdb="500", season=None)])
    entries, key = idx.resolve({"tvdb_id": "500"}, media_type="show")
    assert key == "TVDB" and [e["plex_id"] for e in entries] == [10]


def test_guids_accepts_json_string():
    row = _movie(1, "Movies", tmdb="42")
    row["guids"] = json.dumps(row["guids"])  # stored form
    idx = PlexMediaIndex([row])
    entries, key = idx.resolve({"tmdb_id": "42"}, media_type="movie")
    assert key == "TMDB" and len(entries) == 1


def test_malformed_row_does_not_abort_build():
    idx = PlexMediaIndex([{"asset_type": "movie"}, _movie(1, "Movies", tmdb="42")])
    entries, _ = idx.resolve({"tmdb_id": "42"}, media_type="movie")
    assert len(entries) == 1


def test_is_empty():
    assert PlexMediaIndex([]).is_empty()
    assert not PlexMediaIndex([_movie(1, "Movies", tmdb="42")]).is_empty()

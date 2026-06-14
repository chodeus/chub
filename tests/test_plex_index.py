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


# --- music: artists + albums ---


def _artist(plex_id, lib, *, mbid=None, title="REZZ", norm="rezz"):
    guids = {"mbid": mbid} if mbid else {}
    return {
        "plex_id": plex_id,
        "instance_name": "plex1",
        "asset_type": "artist",
        "library_name": lib,
        "title": title,
        "normalized_title": norm,
        "season_number": None,
        "guids": guids,
    }


def _album(plex_id, lib, *, mbid=None, title="Hits", norm="hits", parent="REZZ"):
    guids = {"mbid": mbid} if mbid else {}
    from backend.util.normalization import normalize_titles

    return {
        "plex_id": plex_id,
        "instance_name": "plex1",
        "asset_type": "album",
        "library_name": lib,
        "title": title,
        "normalized_title": norm,
        "parent_title": parent,
        "parent_normalized_title": normalize_titles(parent),
        "season_number": None,
        "guids": guids,
    }


def test_artist_resolves_by_mbid_first():
    idx = PlexMediaIndex([_artist(1, "Music", mbid="art-1")])
    entries, key = idx.resolve(
        {"musicbrainz_id": "art-1", "title": "Wrong"}, media_type="artist"
    )
    assert key == "MBID" and [e["plex_id"] for e in entries] == [1]


def test_artist_title_fallback():
    idx = PlexMediaIndex([_artist(1, "Music", title="REZZ", norm="rezz")])
    entries, key = idx.resolve({"title": "REZZ"}, media_type="artist")
    assert key == "TITLE" and [e["plex_id"] for e in entries] == [1]


def test_album_resolves_by_mbid_first():
    idx = PlexMediaIndex([_album(5, "Music", mbid="alb-1")])
    entries, key = idx.resolve(
        {"musicbrainz_id": "alb-1", "title": "x", "parent_title": "y"},
        media_type="album",
    )
    assert key == "MBID" and [e["plex_id"] for e in entries] == [5]


def test_album_title_is_parent_scoped_no_cross_artist_collision():
    # Two artists both have a "Greatest Hits" album with no MBID — a bare title
    # match would collide; parent-scoping keeps them distinct.
    idx = PlexMediaIndex(
        [
            _album(1, "Music", title="Greatest Hits", norm="greatesthits",
                   parent="Queen"),
            _album(2, "Music", title="Greatest Hits", norm="greatesthits",
                   parent="ABBA"),
        ]
    )
    entries, key = idx.resolve(
        {"title": "Greatest Hits", "parent_title": "Queen"}, media_type="album"
    )
    assert key == "TITLE"
    assert [e["plex_id"] for e in entries] == [1]


def test_album_type_separation_from_artist():
    idx = PlexMediaIndex([_artist(1, "Music", mbid="shared")])
    # An album lookup against an index holding only an artist resolves nothing
    # even on a shared id value.
    entries, key = idx.resolve(
        {"musicbrainz_id": "shared", "title": "x"}, media_type="album"
    )
    assert entries == [] and key is None


def test_is_empty_includes_music():
    assert not PlexMediaIndex([_artist(1, "Music", mbid="a")]).is_empty()
    assert not PlexMediaIndex([_album(1, "Music", mbid="a")]).is_empty()


def test_artist_mbid_match_is_case_insensitive():
    # Plex guid may be mixed-case; the asset MBID (from extract_mbid / Lidarr)
    # is lower-case. The index must still match.
    idx = PlexMediaIndex([_artist(1, "Music", mbid="ABCDEF12-3456-7890-ABCD-EF1234567890")])
    entries, key = idx.resolve(
        {"musicbrainz_id": "abcdef12-3456-7890-abcd-ef1234567890"},
        media_type="artist",
    )
    assert key == "MBID" and [e["plex_id"] for e in entries] == [1]


def test_album_mbid_match_is_case_insensitive():
    idx = PlexMediaIndex([_album(1, "Music", mbid="AAAA1111-2222-3333-4444-555566667777")])
    entries, key = idx.resolve(
        {"musicbrainz_id": "aaaa1111-2222-3333-4444-555566667777", "title": "x"},
        media_type="album",
    )
    assert key == "MBID" and [e["plex_id"] for e in entries] == [1]

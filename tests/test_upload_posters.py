"""Tests for backend/util/upload_posters.py — static index + match helpers."""

import hashlib


from backend.util.upload_posters import PosterUploader


# --- _build_indexes ---


def test_build_indexes_movie_by_title_and_guids():
    cache = [
        {
            "asset_type": "movie",
            "normalized_title": "inception",
            "guids": {"tmdb": "27205", "imdb": "tt1375666"},
        }
    ]
    movie_idx, show_idx, season_idx, coll_idx = PosterUploader._build_indexes(cache)
    assert "title:inception" in movie_idx
    assert "tmdb:27205" in movie_idx
    assert "imdb:tt1375666" in movie_idx
    assert show_idx == {} and season_idx == {} and coll_idx == {}


def test_build_indexes_show_with_no_season_indexed_as_show():
    cache = [
        {
            "asset_type": "show",
            "normalized_title": "showname",
            "season_number": None,
            "guids": {"tvdb": "999"},
        }
    ]
    _, show_idx, season_idx, _ = PosterUploader._build_indexes(cache)
    assert "title:showname" in show_idx
    assert "tvdb:999" in show_idx
    assert season_idx == {}


def test_build_indexes_season_indexed_separately():
    cache = [
        {
            "asset_type": "show",
            "normalized_title": "showname",
            "season_number": 2,
            "guids": {"tvdb": "999"},
        }
    ]
    _, show_idx, season_idx, _ = PosterUploader._build_indexes(cache)
    assert show_idx == {}
    assert "title:showname:S2" in season_idx
    assert "tvdb:999:S2" in season_idx


def test_build_indexes_collection():
    cache = [{"asset_type": "collection", "normalized_title": "marvelcinematic"}]
    _, _, _, coll_idx = PosterUploader._build_indexes(cache)
    assert "title:marvelcinematic" in coll_idx


def test_build_indexes_parses_json_guids_string():
    """guids serialized as JSON string should still index by id."""
    cache = [
        {
            "asset_type": "movie",
            "normalized_title": "movie",
            "guids": '{"tmdb": "1", "imdb": "tt2"}',
        }
    ]
    movie_idx, *_ = PosterUploader._build_indexes(cache)
    assert "tmdb:1" in movie_idx
    assert "imdb:tt2" in movie_idx


def test_build_indexes_tolerates_broken_entries():
    """A single bad entry should not break the whole index build."""
    cache = [
        None,  # type: ignore[list-item] — defensive against bad cache data
        {"asset_type": "movie", "normalized_title": "good", "guids": {}},
    ]
    movie_idx, *_ = PosterUploader._build_indexes(cache)
    assert "title:good" in movie_idx


# --- match_asset ---


def test_match_asset_returns_first_priority_hit():
    index = {"tmdb:1": {"data": "by_tmdb"}, "title:x": {"data": "by_title"}}
    asset, key = PosterUploader.match_asset(
        index, ["tmdb", "title"], {"tmdb": "1", "title": "x"}
    )
    assert asset == {"data": "by_tmdb"}
    assert key == "TMDB"


def test_match_asset_falls_back_to_secondary():
    index = {"title:x": {"data": "by_title"}}
    asset, key = PosterUploader.match_asset(
        index, ["tmdb", "title"], {"tmdb": "1", "title": "x"}
    )
    assert asset == {"data": "by_title"}
    assert key == "TITLE"


def test_match_asset_no_match():
    asset, key = PosterUploader.match_asset({}, ["tmdb"], {"tmdb": "1"})
    assert asset is None and key is None


def test_match_asset_skips_missing_values():
    index = {"title:x": {"data": "x"}}
    asset, key = PosterUploader.match_asset(
        index, ["tmdb", "title"], {"title": "x"}  # no tmdb value
    )
    assert asset == {"data": "x"}


# --- _compute_file_hash ---


def test_compute_file_hash_dry_run_returns_placeholder():
    assert (
        PosterUploader._compute_file_hash("/nonexistent", dry_run=True)
        == "dry_run_hash"
    )


def test_compute_file_hash_real_file(tmp_path):
    p = tmp_path / "poster.jpg"
    p.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert PosterUploader._compute_file_hash(str(p)) == expected


def test_compute_file_hash_missing_file_returns_none():
    assert PosterUploader._compute_file_hash("/no/such/file") is None


# --- _has_overlay ---


def test_has_overlay_list_form():
    assert PosterUploader._has_overlay({"labels": ["Overlay", "Other"]}) is True
    assert PosterUploader._has_overlay({"labels": ["Other"]}) is False


def test_has_overlay_json_string_form():
    assert PosterUploader._has_overlay({"labels": '["Overlay"]'}) is True


def test_has_overlay_invalid_json_treated_as_empty():
    assert PosterUploader._has_overlay({"labels": "not-json"}) is False


def test_has_overlay_missing_labels():
    assert PosterUploader._has_overlay({}) is False


# --- inter-upload throttle (#d4d1896) ---


def test_throttle_sleeps_when_configured(monkeypatch):
    from types import SimpleNamespace
    import backend.util.upload_posters as up_mod

    up = object.__new__(PosterUploader)
    up.config = SimpleNamespace(upload_delay_ms=50)
    calls = []
    monkeypatch.setattr(up_mod.time, "sleep", lambda s: calls.append(s))
    up._throttle()
    assert calls == [0.05]


def test_throttle_noop_when_zero(monkeypatch):
    from types import SimpleNamespace
    import backend.util.upload_posters as up_mod

    up = object.__new__(PosterUploader)
    up.config = SimpleNamespace(upload_delay_ms=0)
    calls = []
    monkeypatch.setattr(up_mod.time, "sleep", lambda s: calls.append(s))
    up._throttle()
    assert calls == []

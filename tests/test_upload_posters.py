"""Tests for backend/util/upload_posters.py — static index + match helpers."""

import hashlib
import json


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
    index = {"tmdb:1": [{"data": "by_tmdb"}], "title:x": [{"data": "by_title"}]}
    assets, key = PosterUploader.match_asset(
        index, ["tmdb", "title"], {"tmdb": "1", "title": "x"}
    )
    assert assets == [{"data": "by_tmdb"}]
    assert key == "TMDB"


def test_match_asset_falls_back_to_secondary():
    index = {"title:x": [{"data": "by_title"}]}
    assets, key = PosterUploader.match_asset(
        index, ["tmdb", "title"], {"tmdb": "1", "title": "x"}
    )
    assert assets == [{"data": "by_title"}]
    assert key == "TITLE"


def test_match_asset_no_match():
    assets, key = PosterUploader.match_asset({}, ["tmdb"], {"tmdb": "1"})
    assert assets == [] and key is None


def test_match_asset_skips_missing_values():
    index = {"title:x": [{"data": "x"}]}
    assets, key = PosterUploader.match_asset(
        index, ["tmdb", "title"], {"title": "x"}  # no tmdb value
    )
    assert assets == [{"data": "x"}]


def test_build_and_match_same_title_in_multiple_libraries():
    """A movie that lives in two enabled libraries on one instance (e.g. an HD
    and a 4K library) must index both rows under the shared guid so the poster
    can be uploaded to every library, not just the last one scanned."""
    cache = [
        {
            "asset_type": "movie",
            "normalized_title": "dune",
            "title": "Dune",
            "library_name": "Movies",
            "guids": {"tmdb": "438631"},
        },
        {
            "asset_type": "movie",
            "normalized_title": "dune",
            "title": "Dune",
            "library_name": "Movies 4K",
            "guids": {"tmdb": "438631"},
        },
    ]
    movie_idx, *_ = PosterUploader._build_indexes(cache)
    assert len(movie_idx["tmdb:438631"]) == 2
    assert len(movie_idx["title:dune"]) == 2

    assets, key = PosterUploader.match_asset(
        movie_idx, ["tmdb", "title"], {"tmdb": "438631", "title": "dune"}
    )
    assert key == "TMDB"
    assert {a["library_name"] for a in assets} == {"Movies", "Movies 4K"}


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


# --- _sync_single_asset uploads to every matched library ---


def test_sync_single_asset_uploads_to_all_libraries(tmp_path):
    """A movie matched in two libraries gets its poster pushed to both, the DB
    is updated once, and the result reports both library names."""
    from types import SimpleNamespace

    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    updates = []

    class FakePlex:
        def __init__(self):
            self.uploads = []

        def upload_poster(self, *, library_name, item_title, **kw):
            self.uploads.append(library_name)
            return True

        def remove_label(self, *a, **k):
            pass

    fake_plex = FakePlex()
    up = object.__new__(PosterUploader)
    up.force = True  # bypass the mtime/hash skip so the upload path runs
    up.config = SimpleNamespace(upload_delay_ms=0)
    up.logger = SimpleNamespace(warning=lambda *a, **k: None)
    up.db = SimpleNamespace(
        media=SimpleNamespace(update=lambda **kw: updates.append(kw))
    )

    index = {
        "tmdb:438631": [
            {"library_name": "Movies", "title": "Dune", "year": "2021"},
            {"library_name": "Movies 4K", "title": "Dune", "year": "2021"},
        ]
    }
    asset = {
        "title": "Dune",
        "asset_type": "movie",
        "tmdb_id": 438631,
        "renamed_file": str(poster),
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=fake_plex,
        index=index,
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.success is True
    assert result.action == "updated"
    assert fake_plex.uploads == ["Movies", "Movies 4K"]
    assert result.library_name == "Movies, Movies 4K"
    assert len(updates) == 1  # DB updated once, not per library


def test_sync_single_asset_dedupes_same_library(tmp_path):
    """Two index rows for the same library (e.g. unmerged copies) trigger only
    one upload_poster call — _locate_targets already covers copies in a library."""
    from types import SimpleNamespace

    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    class FakePlex:
        def __init__(self):
            self.uploads = []

        def upload_poster(self, *, library_name, **kw):
            self.uploads.append(library_name)
            return True

        def remove_label(self, *a, **k):
            pass

    fake_plex = FakePlex()
    up = object.__new__(PosterUploader)
    up.force = True
    up.config = SimpleNamespace(upload_delay_ms=0)
    up.logger = SimpleNamespace(warning=lambda *a, **k: None)
    up.db = SimpleNamespace(media=SimpleNamespace(update=lambda **kw: None))

    index = {
        "tmdb:438631": [
            {"library_name": "Movies", "title": "Dune", "year": "2021"},
            {"library_name": "Movies", "title": "Dune", "year": "2021"},
        ]
    }
    asset = {
        "title": "Dune",
        "asset_type": "movie",
        "tmdb_id": 438631,
        "renamed_file": str(poster),
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=fake_plex,
        index=index,
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.success is True
    assert fake_plex.uploads == ["Movies"]


# --- per-library skip tracking (hybrid: posterflow-style uploaded_libraries) ---


def _two_library_index():
    return {
        "tmdb:438631": [
            {"library_name": "Movies", "title": "Dune", "year": "2021"},
            {"library_name": "Movies 4K", "title": "Dune", "year": "2021"},
        ]
    }


def _make_uploader(updates):
    from types import SimpleNamespace

    up = object.__new__(PosterUploader)
    up.force = False
    up.config = SimpleNamespace(upload_delay_ms=0)
    up.logger = SimpleNamespace(warning=lambda *a, **k: None)
    up.db = SimpleNamespace(
        media=SimpleNamespace(update=lambda **kw: updates.append(kw))
    )
    return up


class _RecordingPlex:
    def __init__(self):
        self.uploads = []

    def upload_poster(self, *, library_name, **kw):
        self.uploads.append(library_name)
        return True

    def remove_label(self, *a, **k):
        pass


def test_sync_skips_when_all_libraries_already_covered(tmp_path):
    """Unchanged file + every matched library already recorded => true skip,
    no upload calls."""
    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    updates = []
    up = _make_uploader(updates)
    plex = _RecordingPlex()

    asset = {
        "title": "Dune",
        "asset_type": "movie",
        "tmdb_id": 438631,
        "renamed_file": str(poster),
        "file_mtime": poster.stat().st_mtime,  # mtime fast-path matches
        "uploaded_libraries": '["Movies", "Movies 4K"]',
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=plex,
        index=_two_library_index(),
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.action == "skipped"
    assert plex.uploads == []
    assert updates == []  # nothing re-persisted on a clean skip


def test_sync_backfills_only_missing_library(tmp_path):
    """Unchanged file but a library is missing it => upload only to that
    library and grow the recorded set (no forced run needed)."""
    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    updates = []
    up = _make_uploader(updates)
    plex = _RecordingPlex()

    asset = {
        "title": "Dune",
        "asset_type": "movie",
        "tmdb_id": 438631,
        "renamed_file": str(poster),
        "file_mtime": poster.stat().st_mtime,
        "uploaded_libraries": '["Movies"]',  # 4K not yet covered
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=plex,
        index=_two_library_index(),
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.success is True
    assert plex.uploads == ["Movies 4K"]  # only the missing library
    assert result.library_name == "Movies 4K"
    # Recorded set grows to both libraries.
    assert len(updates) == 1
    assert json.loads(updates[0]["uploaded_libraries"]) == ["Movies", "Movies 4K"]


def test_sync_legacy_row_backfills_all_libraries(tmp_path):
    """A row from before this feature (uploaded_libraries NULL) auto-backfills
    every library on the next run, even with an unchanged file."""
    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    updates = []
    up = _make_uploader(updates)
    plex = _RecordingPlex()

    asset = {
        "title": "Dune",
        "asset_type": "movie",
        "tmdb_id": 438631,
        "renamed_file": str(poster),
        "file_mtime": poster.stat().st_mtime,
        # no uploaded_libraries key at all
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=plex,
        index=_two_library_index(),
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.success is True
    assert plex.uploads == ["Movies", "Movies 4K"]
    assert json.loads(updates[0]["uploaded_libraries"]) == ["Movies", "Movies 4K"]


def test_sync_dry_run_does_not_persist_libraries(tmp_path):
    """A dry-run upload must not record libraries as covered — otherwise a
    later real run would wrongly skip them."""
    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    updates = []
    up = _make_uploader(updates)
    plex = _RecordingPlex()

    asset = {
        "title": "Dune",
        "asset_type": "movie",
        "tmdb_id": 438631,
        "renamed_file": str(poster),
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=plex,
        index=_two_library_index(),
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=True,
    )

    assert result.success is True
    # DB updated, but uploaded_libraries stays None in dry-run.
    assert len(updates) == 1
    assert updates[0]["uploaded_libraries"] is None


def test_parse_uploaded_libraries_tolerant():
    assert PosterUploader._parse_uploaded_libraries(None) == set()
    assert PosterUploader._parse_uploaded_libraries("") == set()
    assert PosterUploader._parse_uploaded_libraries("not-json") == set()
    assert PosterUploader._parse_uploaded_libraries('["A", "B"]') == {"A", "B"}
    assert PosterUploader._parse_uploaded_libraries(["A", "B"]) == {"A", "B"}
    assert PosterUploader._parse_uploaded_libraries('{"x": 1}') == set()

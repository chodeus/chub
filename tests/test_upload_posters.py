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
    movie_idx, show_idx, season_idx, coll_idx, artist_idx, album_idx = (
        PosterUploader._build_indexes(cache)
    )
    assert "title:inception" in movie_idx
    assert "tmdb:27205" in movie_idx
    assert "imdb:tt1375666" in movie_idx
    assert show_idx == {} and season_idx == {} and coll_idx == {}
    assert artist_idx == {} and album_idx == {}


def test_build_indexes_show_with_no_season_indexed_as_show():
    cache = [
        {
            "asset_type": "show",
            "normalized_title": "showname",
            "season_number": None,
            "guids": {"tvdb": "999"},
        }
    ]
    _, show_idx, season_idx, *_ = PosterUploader._build_indexes(cache)
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
    _, show_idx, season_idx, *_ = PosterUploader._build_indexes(cache)
    assert show_idx == {}
    assert "title:showname:S2" in season_idx
    assert "tvdb:999:S2" in season_idx


def test_build_indexes_collection():
    cache = [{"asset_type": "collection", "normalized_title": "marvelcinematic"}]
    _, _, _, coll_idx, _, _ = PosterUploader._build_indexes(cache)
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
        index,
        ["tmdb", "title"],
        {"title": "x"},  # no tmdb value
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


# --- _note_year_discrepancy ---


def _discrepancy_uploader():
    """Bare uploader with just the state _note_year_discrepancy touches."""
    from types import SimpleNamespace

    up = object.__new__(PosterUploader)
    up._year_discrepancies = []
    up.logger = SimpleNamespace(warning=lambda *a, **k: None)
    return up


def test_year_discrepancy_recorded_when_guid_match_year_differs():
    up = _discrepancy_uploader()
    up._note_year_discrepancy(
        {"title": "Michael", "year": 2025},
        [{"year": 2027, "library_name": "Movies"}],
        "TMDB",
    )
    assert up._year_discrepancies == [
        {
            "title": "Michael",
            "folder_year": 2025,
            "plex_year": 2027,
            "match_type": "TMDB",
        }
    ]


def test_year_discrepancy_ignored_within_tolerance():
    """±1 year is normal *arr/Plex lag (production vs release) — not flagged."""
    up = _discrepancy_uploader()
    up._note_year_discrepancy(
        {"title": "Wicked", "year": 2024},
        [{"year": 2025, "library_name": "Movies"}],
        "TMDB",
    )
    assert up._year_discrepancies == []


def test_year_discrepancy_ignored_for_title_match():
    """TITLE matches are already year-disambiguated upstream, so never flagged."""
    up = _discrepancy_uploader()
    up._note_year_discrepancy(
        {"title": "Hairspray", "year": 1988},
        [{"year": 2007, "library_name": "Movies"}],
        "TITLE",
    )
    assert up._year_discrepancies == []


def test_year_discrepancy_ignored_without_folder_year():
    up = _discrepancy_uploader()
    up._note_year_discrepancy(
        {"title": "Unknown", "year": None},
        [{"year": 2020, "library_name": "Movies"}],
        "TVDB",
    )
    assert up._year_discrepancies == []


def test_year_discrepancy_recorded_once_per_asset():
    """Multiple library copies of the same mismatched item record one entry."""
    up = _discrepancy_uploader()
    up._note_year_discrepancy(
        {"title": "Michael", "year": 2025},
        [
            {"year": 2027, "library_name": "Movies"},
            {"year": 2027, "library_name": "Movies 4K"},
        ],
        "IMDB",
    )
    assert len(up._year_discrepancies) == 1


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


def test_sync_single_asset_live_fallback_when_absent_from_cache(tmp_path):
    """A brand-new import that isn't in the cached index still uploads: the LIVE
    fallback targets the instance's movie libraries (skipping show libraries) and
    pushes to the one(s) that actually hold it. This is the webhook/instant path
    that must not depend on the stale plex_media_cache snapshot."""
    from types import SimpleNamespace

    poster = tmp_path / "The Shawshank Redemption (1994).jpg"
    poster.write_bytes(b"poster-bytes")

    updates = []

    class FakePlex:
        url = "http://plex:32400"

        def __init__(self):
            self.uploads = []

        def get_libraries(self):
            return ["Films", "Films 4K", "TV Programmes"]

        def section_type(self, name):
            return "show" if name == "TV Programmes" else "movie"

        def upload_poster(self, *, library_name, item_title, **kw):
            # Only "Films" actually holds the movie; the live title+year search
            # finds nothing in the others, so upload_poster returns False there.
            if library_name == "Films":
                self.uploads.append(library_name)
                return True
            return False

        def remove_label(self, *a, **k):
            pass

    fake_plex = FakePlex()
    up = object.__new__(PosterUploader)
    up.force = True
    up.config = SimpleNamespace(upload_delay_ms=0)
    up.logger = SimpleNamespace(
        warning=lambda *a, **k: None, debug=lambda *a, **k: None
    )
    up.db = SimpleNamespace(
        media=SimpleNamespace(update=lambda **kw: updates.append(kw))
    )
    up._live_lib_types = {}

    asset = {
        "title": "The Shawshank Redemption",
        "asset_type": "movie",
        "year": "1994",
        "tmdb_id": 278,
        "instance_name": "Chodeus",
        "renamed_file": str(poster),
    }

    result = up._sync_single_asset(
        asset=asset,
        plex_client=fake_plex,
        index={},  # EMPTY cache → the live fallback must carry it
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.success is True
    assert result.action == "updated"
    assert result.match_type == "LIVE"
    assert fake_plex.uploads == ["Films"]  # only the library that has it
    assert "TV Programmes" not in fake_plex.uploads  # wrong type never targeted


def test_sync_single_asset_no_live_match_reports_not_found(tmp_path):
    """When neither the cache nor a live search finds the item in any library,
    it still reports the clear 'No matching Plex entry found' failure."""
    from types import SimpleNamespace

    poster = tmp_path / "Ghost Movie (2099).jpg"
    poster.write_bytes(b"poster-bytes")

    class FakePlex:
        url = "http://plex:32400"

        def get_libraries(self):
            return ["Films"]

        def section_type(self, name):
            return "movie"

        def upload_poster(self, **kw):
            return False  # live search finds nothing anywhere

        def remove_label(self, *a, **k):
            pass

    up = object.__new__(PosterUploader)
    up.force = True
    up.config = SimpleNamespace(upload_delay_ms=0)
    up.logger = SimpleNamespace(
        warning=lambda *a, **k: None, debug=lambda *a, **k: None
    )
    up.db = SimpleNamespace(media=SimpleNamespace(update=lambda **kw: None))
    up._live_lib_types = {}

    result = up._sync_single_asset(
        asset={
            "title": "Ghost Movie",
            "asset_type": "movie",
            "year": "2099",
            "instance_name": "Chodeus",
            "renamed_file": str(poster),
        },
        plex_client=FakePlex(),
        index={},
        priority_keys=["tmdb", "imdb", "title"],
        dry_run=False,
    )

    assert result.success is False
    assert result.reason in ("Upload to Plex failed", "No matching Plex entry found")


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


def _plex_id_uploader():
    from types import SimpleNamespace

    class FakePlex:
        def __init__(self):
            self.uploads = []

        def upload_poster(self, *, library_name, **kw):
            self.uploads.append((library_name, kw.get("plex_id")))
            return True

        def remove_label(self, *a, **k):
            pass

    up = object.__new__(PosterUploader)
    up.force = True
    up.config = SimpleNamespace(upload_delay_ms=0)
    up.logger = SimpleNamespace(warning=lambda *a, **k: None)
    up.db = SimpleNamespace(media=SimpleNamespace(update=lambda **kw: None))
    return up, FakePlex()


def test_sync_single_asset_uploads_to_all_unmerged_copies_same_library(tmp_path):
    """Two un-merged copies in the SAME library carry distinct plex_ids —
    ratingKey resolution fetches exactly one item, so each copy needs its own
    upload call (library-only dedupe silently skipped the sibling)."""
    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    up, fake_plex = _plex_id_uploader()
    index = {
        "tmdb:438631": [
            {
                "library_name": "Movies",
                "title": "Dune",
                "year": "2021",
                "plex_id": "111",
            },
            {
                "library_name": "Movies",
                "title": "Dune",
                "year": "2021",
                "plex_id": "222",
            },
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
    assert {pid for _, pid in fake_plex.uploads} == {"111", "222"}
    assert [lib for lib, _ in fake_plex.uploads] == ["Movies", "Movies"]
    assert result.library_name == "Movies"  # no "Movies, Movies" label


def test_sync_single_asset_dedupes_identical_plex_id(tmp_path):
    """Same library AND same plex_id is one true target — still one upload."""
    poster = tmp_path / "Dune (2021).jpg"
    poster.write_bytes(b"poster-bytes")

    up, fake_plex = _plex_id_uploader()
    index = {
        "tmdb:438631": [
            {
                "library_name": "Movies",
                "title": "Dune",
                "year": "2021",
                "plex_id": "111",
            },
            {
                "library_name": "Movies",
                "title": "Dune",
                "year": "2021",
                "plex_id": "111",
            },
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
    assert fake_plex.uploads == [("Movies", "111")]


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
    # Dry-run must not touch the DB at all — writing the hash/mtime would make a
    # later real run skip the asset as already uploaded.
    assert len(updates) == 0


def test_parse_uploaded_libraries_tolerant():
    assert PosterUploader._parse_uploaded_libraries(None) == set()
    assert PosterUploader._parse_uploaded_libraries("") == set()
    assert PosterUploader._parse_uploaded_libraries("not-json") == set()
    assert PosterUploader._parse_uploaded_libraries('["A", "B"]') == {"A", "B"}
    assert PosterUploader._parse_uploaded_libraries(["A", "B"]) == {"A", "B"}
    assert PosterUploader._parse_uploaded_libraries('{"x": 1}') == set()


# --- _write_music_sidecar (LMA disk sidecars, atomic overwrite) ---


def _sidecar_uploader(warnings=None):
    from types import SimpleNamespace

    up = object.__new__(PosterUploader)
    up.logger = SimpleNamespace(
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: warnings.append(a) if warnings is not None else None,
    )
    return up


def _tmp_litter(folder):
    return [p for p in folder.iterdir() if ".chub-tmp-" in p.name]


def test_write_music_sidecar_writes_cover(tmp_path):
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"poster-bytes")
    folder = tmp_path / "album"
    folder.mkdir()
    entry = {"file_paths": [str(folder)], "title": "X"}

    up = _sidecar_uploader()
    up._write_music_sidecar("album", str(poster), entry, dry_run=False)
    assert (folder / "cover.jpg").read_bytes() == b"poster-bytes"

    up._write_music_sidecar("artist", str(poster), entry, dry_run=False)
    assert (folder / "artist-poster.jpg").read_bytes() == b"poster-bytes"

    assert _tmp_litter(folder) == []


def test_write_music_sidecar_failure_preserves_existing_cover(tmp_path, monkeypatch):
    """A crash mid-copy (partial write + OSError) must leave the user's
    existing cover untouched, warn instead of raising, and leave no temp
    litter in the music folder."""
    import backend.util.upload_posters as up_mod

    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"poster-bytes")
    folder = tmp_path / "album"
    folder.mkdir()
    existing = folder / "cover.jpg"
    existing.write_bytes(b"original")
    entry = {"file_paths": [str(folder)], "title": "X"}

    def _partial_copy(src, dst):
        with open(dst, "wb") as fh:
            fh.write(b"part")
        raise OSError("disk full")

    monkeypatch.setattr(up_mod.shutil, "copyfile", _partial_copy)

    warnings = []
    up = _sidecar_uploader(warnings)
    up._write_music_sidecar("album", str(poster), entry, dry_run=False)

    assert existing.read_bytes() == b"original"
    assert warnings, "sidecar failure should warn, not pass silently"
    assert _tmp_litter(folder) == []

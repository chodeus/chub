"""Unit tests for BorderReplacerr's image-border helpers."""

import pytest
from PIL import Image
from types import SimpleNamespace

from backend.modules.border_replacerr import (
    _BUNDLED_BORDERS_DIR,
    BorderReplacerr,
)

from tests.conftest import StubLogger


def _make_br():
    """Build a BorderReplacerr without invoking the full ChubModule init."""
    br = BorderReplacerr.__new__(BorderReplacerr)
    br.logger = StubLogger()
    return br


@pytest.mark.parametrize(
    "display_name,expected",
    [
        ("🎄 Christmas", "christmas"),
        ("🎃 Halloween", "halloween"),
        ("🧧 Lunar New Year", "lunarnewyear"),
        ("🏳️‍🌈 Pride", "pride"),
        ("🍀 St. Patrick's Day", "stpatricks"),
        ("👨‍👧‍👦 Father's Day", "fathersday"),
        # Unknown holidays fall back to alphanumeric slug
        ("🦅 Eagle Scout Day", "eaglescoutday"),
        # Empty / falsy
        ("", None),
        (None, None),
    ],
)
def test_holiday_folder_mapping(display_name, expected):
    br = _make_br()
    assert br._holiday_folder(display_name) == expected


def test_resolve_border_paths_prefers_user_dir(tmp_path, monkeypatch):
    """When both user and bundled files exist, user dir wins."""
    user_root = tmp_path / "config"
    monkeypatch.setenv("CONFIG_DIR", str(user_root))
    monkeypatch.setenv("DOCKER_ENV", "true")

    user_dir = user_root / "borders" / "christmas"
    user_dir.mkdir(parents=True)
    user_file = user_dir / "v1.png"
    Image.new("RGBA", (1000, 1500), (0, 0, 0, 0)).save(user_file)

    br = _make_br()
    resolved = br._resolve_border_paths("🎄 Christmas", ["v1"])
    assert resolved == [str(user_file)]


def test_resolve_border_paths_drops_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("DOCKER_ENV", "true")

    br = _make_br()
    resolved = br._resolve_border_paths("🎄 Christmas", ["does-not-exist"])
    assert resolved == []
    # A warning should have been logged so the user can debug.
    assert any(
        "does-not-exist" in msg for msg in br.logger.messages["warning"]
    )


def test_resolve_border_paths_handles_unknown_holiday(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("DOCKER_ENV", "true")

    br = _make_br()
    # Unknown holiday has no bundled folder — should silently return []
    # rather than blow up.
    assert br._resolve_border_paths("🦅 Eagle Scout Day", ["v1"]) == []


def test_replace_borders_with_image_composites(tmp_path):
    """Smoke-test the alpha-composite path with a synthetic border."""
    # Fake poster: solid red 2000×3000 (will get resized to 1000×1500)
    poster_path = tmp_path / "poster.jpg"
    Image.new("RGB", (2000, 3000), (255, 0, 0)).save(poster_path, "JPEG")

    # Fake border: 1000×1500, opaque blue ring with transparent center
    border_path = tmp_path / "border.png"
    border = Image.new("RGBA", (1000, 1500), (0, 0, 255, 255))
    # Punch out the inner (60, 60)→(940, 1440) rectangle to transparent
    for y in range(60, 1440):
        for x in range(60, 940):
            border.putpixel((x, y), (0, 0, 0, 0))
    border.save(border_path, "PNG")

    out_path = tmp_path / "out.jpg"
    br = _make_br()
    assert br.replace_borders_with_image(
        str(poster_path), str(out_path), str(border_path)
    )
    assert out_path.exists()

    # Verify a corner pixel is blue (border opacity) and the center is red
    # (poster shows through). JPEG is lossy so allow a small per-channel
    # tolerance.
    def _close(actual, expected, tol=5):
        return all(abs(a - e) <= tol for a, e in zip(actual, expected))

    with Image.open(out_path) as result:
        result = result.convert("RGB")
        assert result.size == (1000, 1500)
        assert _close(result.getpixel((10, 10)), (0, 0, 255))
        assert _close(result.getpixel((500, 750)), (255, 0, 0))


def test_replace_borders_with_image_square_target(tmp_path):
    """Album covers are 1:1 — passing target_size=(1000,1000) yields a square
    output rather than the portrait default."""
    poster_path = tmp_path / "cover.jpg"
    Image.new("RGB", (1500, 1500), (0, 255, 0)).save(poster_path, "JPEG")
    border_path = tmp_path / "border.png"
    Image.new("RGBA", (1000, 1000), (0, 0, 0, 0)).save(border_path, "PNG")

    out_path = tmp_path / "out.jpg"
    br = _make_br()
    assert br.replace_borders_with_image(
        str(poster_path), str(out_path), str(border_path), (1000, 1000)
    )
    with Image.open(out_path) as result:
        assert result.size == (1000, 1000)


def test_remove_borders_square_target(tmp_path):
    """remove_borders honours a square target_size for album covers."""
    src = tmp_path / "cover.jpg"
    Image.new("RGB", (1100, 1100), (10, 20, 30)).save(src, "JPEG")
    out_path = tmp_path / "out.jpg"
    br = _make_br()
    assert br.remove_borders(str(src), str(out_path), 25, (1000, 1000))
    with Image.open(out_path) as result:
        assert result.size == (1000, 1000)


def test_bundled_borders_dir_exists():
    """Sanity-check that the bundled asset tree shipped with the module."""
    assert _BUNDLED_BORDERS_DIR.is_dir()
    holidays = {p.name for p in _BUNDLED_BORDERS_DIR.iterdir() if p.is_dir()}
    # Spot-check a handful — full inventory is enforced by the rasterize
    # script + Dockerfile, not the test.
    assert {"christmas", "halloween", "pride"}.issubset(holidays)


# ---- skip-gate primitives (#12) ------------------------------------------


def test_save_if_changed_writes_then_skips_identical(tmp_path):
    """First save writes; an identical re-save is skipped via content compare
    (shallow=False), and no temp files are left behind in the dest dir."""
    br = _make_br()
    dest = tmp_path / "media" / "poster.jpg"
    img = Image.new("RGB", (10, 15), (1, 2, 3))

    assert br._save_if_changed(img, str(dest)) is True
    assert dest.exists()
    # Identical output -> deterministic JPEG bytes -> skip.
    assert br._save_if_changed(img, str(dest)) is False
    # Different output -> rewrite.
    assert br._save_if_changed(Image.new("RGB", (10, 15), (9, 9, 9)), str(dest)) is True

    leftovers = [p.name for p in dest.parent.iterdir() if p.name.startswith(".border-")]
    assert leftovers == []


def test_file_digest_and_safe_stat(tmp_path):
    a = tmp_path / "a.png"
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(a)
    d1 = BorderReplacerr._file_digest(str(a))
    assert d1 and BorderReplacerr._file_digest(str(a)) == d1  # stable
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(a)
    assert BorderReplacerr._file_digest(str(a)) != d1  # content-sensitive
    assert BorderReplacerr._file_digest(str(tmp_path / "missing.png")) == ""
    assert BorderReplacerr._safe_stat(str(a)) is not None
    assert BorderReplacerr._safe_stat(str(tmp_path / "missing.png")) is None


def test_border_state_roundtrip_and_upsert(tmp_path):
    from backend.util.database.border_state import BorderState

    bs = BorderState(logger=StubLogger(), db_path=str(tmp_path / "t.db"))
    n = bs.bulk_record(
        [
            {
                "renamed_file": "/m/a.jpg",
                "source_mtime": 1.5,
                "source_size": 10,
                "variant_sig": "color:8:(255, 0, 0)",
                "updated_at": "t0",
            },
            {
                "renamed_file": "/m/b.jpg",
                "source_mtime": 2.0,
                "source_size": 20,
                "variant_sig": "remove:8",
                "updated_at": "t0",
            },
        ]
    )
    assert n == 2
    m = bs.get_all_map()
    assert set(m) == {"/m/a.jpg", "/m/b.jpg"}
    assert m["/m/a.jpg"]["source_size"] == 10
    assert m["/m/a.jpg"]["variant_sig"] == "color:8:(255, 0, 0)"

    # PK conflict updates in place.
    bs.bulk_record(
        [
            {
                "renamed_file": "/m/a.jpg",
                "source_mtime": 9.0,
                "source_size": 99,
                "variant_sig": "x",
                "updated_at": "t1",
            }
        ]
    )
    m2 = bs.get_all_map()
    assert m2["/m/a.jpg"]["source_size"] == 99
    assert m2["/m/a.jpg"]["variant_sig"] == "x"

    bs.clear()
    assert bs.get_all_map() == {}


# ---- full-library asset collection -----------------------------------------


class _StubTable:
    """Stands in for db.media / db.collection with a get_all()."""

    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


class _StubDB:
    def __init__(self, media=None, collections=None):
        self.media = _StubTable(media or [])
        self.collection = _StubTable(collections or [])


def _make_br_with_config(exclusion_list=None, ignore_folders=None):
    br = _make_br()
    br.config = SimpleNamespace(
        exclusion_list=exclusion_list or [],
        ignore_folders=ignore_folders or [],
    )
    return br


def test_collect_matched_assets_includes_moved_and_collections(tmp_path):
    """The full pass must include matched posters that are ALREADY MOVED
    (renamed_file exists on disk) and matched collections — the exact set
    get_matched_assets() drops. This is the core regression guard."""
    moved_dest = tmp_path / "Movie (2020)" / "poster.jpg"
    moved_dest.parent.mkdir(parents=True)
    moved_dest.write_bytes(b"already-moved")

    media = [
        {
            "title": "Moved Movie",
            "folder": "Movie (2020)",
            "matched": 1,
            "original_file": str(tmp_path / "src" / "movie.jpg"),
            "renamed_file": str(moved_dest),  # exists on disk == "moved"
        },
        {"title": "Unmatched", "folder": "x", "matched": 0},
    ]
    collections = [
        {
            "title": "My Collection",
            "folder": "",
            "matched": 1,
            "original_file": str(tmp_path / "src" / "coll.jpg"),
            "renamed_file": str(tmp_path / "dest" / "My Collection.jpg"),
        }
    ]

    br = _make_br_with_config()
    assets = br._collect_matched_assets(_StubDB(media, collections))

    titles = {a["title"] for a in assets}
    assert titles == {"Moved Movie", "My Collection"}  # moved + collection in; unmatched out


def test_collect_matched_assets_applies_exclusion_and_ignore_filters():
    media = [
        {"title": "Keep", "folder": "keepdir", "matched": 1},
        {"title": "ByTitle", "folder": "okdir", "matched": 1},
        {"title": "ByFolder", "folder": "skipdir", "matched": 1},
    ]
    br = _make_br_with_config(
        exclusion_list=["ByTitle"], ignore_folders=["skipdir"]
    )
    assets = br._collect_matched_assets(_StubDB(media, []))
    assert {a["title"] for a in assets} == {"Keep"}


# ---- selection rule: full-library vs manifest subset -----------------------


@pytest.mark.parametrize(
    "manifest,process_all,reset_all,expected",
    [
        ({"media_cache": [1]}, False, False, False),  # webhook/adhoc subset
        ({"media_cache": [1]}, True, False, True),    # renamerr full run
        ({"media_cache": [1]}, False, True, True),    # holiday transition
        (None, False, False, True),                   # standalone run (no manifest)
    ],
)
def test_should_process_all(manifest, process_all, reset_all, expected):
    assert (
        BorderReplacerr._should_process_all(manifest, process_all, reset_all)
        is expected
    )


# ---- poster_renamerr wiring ------------------------------------------------


def test_renamerr_run_border_replacerr_forwards_process_all(monkeypatch):
    """poster_renamerr.run_border_replacerr must forward process_all into
    BorderReplacerr.run so a full renamerr run sweeps the whole library."""
    import backend.modules.border_replacerr as border_mod
    from backend.modules.poster_renamerr import PosterRenamerr

    captured = {}

    class _FakeBorder:
        def __init__(self, logger=None):
            pass

        def set_job_context(self, *a, **k):
            pass

        def set_progress_window(self, *a, **k):
            pass

        def run(self, manifest=None, process_all=False, manifest_only=False):
            captured["manifest"] = manifest
            captured["process_all"] = process_all
            captured["manifest_only"] = manifest_only

    monkeypatch.setattr(border_mod, "BorderReplacerr", _FakeBorder)

    renamer = PosterRenamerr.__new__(PosterRenamerr)
    renamer.logger = StubLogger()

    manifest = {"media_cache": [1, 2], "collections_cache": []}
    renamer.run_border_replacerr(manifest, process_all=True)

    assert captured["process_all"] is True
    assert captured["manifest"] == manifest
    assert captured["manifest_only"] is False

    # plex apply path: manifest_only forwards too (hard-restricts the sweep).
    renamer.run_border_replacerr(manifest, process_all=False, manifest_only=True)
    assert captured["process_all"] is False
    assert captured["manifest_only"] is True


# ---- end-to-end: full pass borders all, second pass re-encodes nothing -----


def test_full_pass_borders_all_then_skips_unchanged(tmp_path, monkeypatch):
    import backend.modules.border_replacerr as border_mod
    from backend.util.database.border_state import BorderState

    # Real source posters on disk (1000x1500 so border ops are cheap/no-resize).
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    rows = []
    for name in ("alpha", "beta"):
        src = src_dir / f"{name}.jpg"
        Image.new("RGB", (1000, 1500), (10, 20, 30)).save(src, "JPEG")
        rows.append(
            {
                "title": name,
                "folder": name,
                "matched": 1,
                "original_file": str(src),
                "renamed_file": str(dest_dir / f"{name}.jpg"),
            }
        )

    border_state = BorderState(logger=StubLogger(), db_path=str(tmp_path / "b.db"))

    class _FakeDB:
        def __init__(self):
            self.media = _StubTable(rows)
            self.collection = _StubTable([])
            self.holiday = SimpleNamespace(
                get_status=lambda: {"last_active_holiday": None},
                set_status=lambda *a, **k: None,
            )
            self.border = border_state

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(border_mod, "ChubDB", lambda *a, **k: _FakeDB())
    # Notifications are irrelevant here; stub them so the run never touches one.
    monkeypatch.setattr(
        border_mod,
        "NotificationManager",
        lambda *a, **k: SimpleNamespace(send_notification=lambda *a, **k: None),
    )

    br = _make_br()
    br.full_config = SimpleNamespace()
    br.config = SimpleNamespace(
        log_level="info",
        holidays=[],
        border_colors=["#FF0000"],  # color mode
        exclusion_list=[],
        ignore_folders=[],
        dry_run=False,
        border_width=26,
        border_workers=1,  # deterministic, single-threaded
    )

    # Count actual border encodes so we can prove the gate skips the 2nd pass.
    real_replace = BorderReplacerr.replace_borders.__get__(br, BorderReplacerr)
    calls = {"n": 0}

    def _counting_replace(*a, **k):
        calls["n"] += 1
        return real_replace(*a, **k)

    br.replace_borders = _counting_replace

    # First full pass: every asset is bordered and written.
    br.run(process_all=True)
    assert calls["n"] == 2
    dest_alpha = dest_dir / "alpha.jpg"
    dest_beta = dest_dir / "beta.jpg"
    assert dest_alpha.exists() and dest_beta.exists()
    first_bytes = (dest_alpha.read_bytes(), dest_beta.read_bytes())

    # Second identical full pass: gate skips both -> no re-encode, no rewrite.
    calls["n"] = 0
    br.run(process_all=True)
    assert calls["n"] == 0  # the skip-gate prevented any encode
    assert (dest_alpha.read_bytes(), dest_beta.read_bytes()) == first_bytes


def test_full_pass_skips_poster_with_missing_source(tmp_path, monkeypatch):
    """A matched poster whose source file is gone from disk must be counted
    as 'skipped' (no encode attempt, no dest written), not run through the
    encoder and tallied as 'failed'."""
    import backend.modules.border_replacerr as border_mod
    from backend.util.database.border_state import BorderState

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    row = {
        "title": "ghost",
        "folder": "ghost",
        "matched": 1,
        "original_file": str(tmp_path / "src" / "ghost.jpg"),  # never created
        "renamed_file": str(dest_dir / "ghost.jpg"),
    }
    border_state = BorderState(logger=StubLogger(), db_path=str(tmp_path / "b.db"))

    class _FakeDB:
        def __init__(self):
            self.media = _StubTable([row])
            self.collection = _StubTable([])
            self.holiday = SimpleNamespace(
                get_status=lambda: {"last_active_holiday": None},
                set_status=lambda *a, **k: None,
            )
            self.border = border_state

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(border_mod, "ChubDB", lambda *a, **k: _FakeDB())
    monkeypatch.setattr(
        border_mod,
        "NotificationManager",
        lambda *a, **k: SimpleNamespace(send_notification=lambda *a, **k: None),
    )

    br = _make_br()
    br.full_config = SimpleNamespace()
    br.config = SimpleNamespace(
        log_level="info",
        holidays=[],
        border_colors=["#FF0000"],
        exclusion_list=[],
        ignore_folders=[],
        dry_run=False,
        border_width=26,
        border_workers=1,
    )

    calls = {"n": 0}
    real_replace = BorderReplacerr.replace_borders.__get__(br, BorderReplacerr)

    def _counting(*a, **k):
        calls["n"] += 1
        return real_replace(*a, **k)

    br.replace_borders = _counting

    br.run(process_all=True)
    assert calls["n"] == 0  # missing source -> skipped before any encode
    assert not (dest_dir / "ghost.jpg").exists()


def test_subset_pass_only_borders_manifest_items(tmp_path, monkeypatch):
    """With process_all=False and a manifest, only manifest items are
    bordered; a matched, already-moved poster NOT in the manifest is left
    untouched (webhook/adhoc stays subset-only)."""
    import backend.modules.border_replacerr as border_mod
    from backend.util.database.border_state import BorderState

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    def _mkrow(id_, name):
        src = src_dir / f"{name}.jpg"
        Image.new("RGB", (1000, 1500), (10, 20, 30)).save(src, "JPEG")
        return {
            "id": id_,
            "title": name,
            "folder": name,
            "matched": 1,
            "original_file": str(src),
            "renamed_file": str(dest_dir / f"{name}.jpg"),
        }

    in_manifest = _mkrow(1, "inman")
    out_manifest = _mkrow(2, "outman")
    by_id = {1: in_manifest, 2: out_manifest}
    border_state = BorderState(logger=StubLogger(), db_path=str(tmp_path / "b.db"))

    class _MediaTable:
        def get_by_id(self, i):
            return by_id.get(i)

        def get_all(self):
            return [in_manifest, out_manifest]

    class _CollTable:
        def get_by_id(self, i):
            return None

        def get_all(self):
            return []

    class _FakeDB:
        def __init__(self):
            self.media = _MediaTable()
            self.collection = _CollTable()
            self.holiday = SimpleNamespace(
                get_status=lambda: {"last_active_holiday": None},
                set_status=lambda *a, **k: None,
            )
            self.border = border_state

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(border_mod, "ChubDB", lambda *a, **k: _FakeDB())
    monkeypatch.setattr(
        border_mod,
        "NotificationManager",
        lambda *a, **k: SimpleNamespace(send_notification=lambda *a, **k: None),
    )

    br = _make_br()
    br.full_config = SimpleNamespace()
    br.config = SimpleNamespace(
        log_level="info",
        holidays=[],
        border_colors=["#FF0000"],
        exclusion_list=[],
        ignore_folders=[],
        dry_run=False,
        border_width=26,
        border_workers=1,
    )

    manifest = {"media_cache": [1], "collections_cache": []}
    br.run(manifest, process_all=False)

    assert (dest_dir / "inman.jpg").exists()        # manifest item bordered
    assert not (dest_dir / "outman.jpg").exists()   # non-manifest item untouched


def _subset_harness(tmp_path, monkeypatch, exclusion_list=None):
    """Shared setup for manifest-mode runs: two real source posters (ids 1/2),
    a fake DB, notifications stubbed. Returns (br, dest_dir, rows_by_id)."""
    import backend.modules.border_replacerr as border_mod
    from backend.util.database.border_state import BorderState

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    def _mkrow(id_, name):
        src = src_dir / f"{name}.jpg"
        Image.new("RGB", (1000, 1500), (10, 20, 30)).save(src, "JPEG")
        return {
            "id": id_,
            "title": name,
            "folder": name,
            "matched": 1,
            "original_file": str(src),
            "renamed_file": str(dest_dir / f"{name}.jpg"),
        }

    by_id = {1: _mkrow(1, "inman"), 2: _mkrow(2, "outman")}
    border_state = BorderState(logger=StubLogger(), db_path=str(tmp_path / "b.db"))

    class _MediaTable:
        def get_by_id(self, i):
            return by_id.get(i)

        def get_all(self):
            return list(by_id.values())

    class _CollTable:
        def get_by_id(self, i):
            return None

        def get_all(self):
            return []

    class _FakeDB:
        def __init__(self):
            self.media = _MediaTable()
            self.collection = _CollTable()
            self.holiday = SimpleNamespace(
                get_status=lambda: {"last_active_holiday": None},
                set_status=lambda *a, **k: None,
            )
            self.border = border_state

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(border_mod, "ChubDB", lambda *a, **k: _FakeDB())
    monkeypatch.setattr(
        border_mod,
        "NotificationManager",
        lambda *a, **k: SimpleNamespace(send_notification=lambda *a, **k: None),
    )

    br = _make_br()
    br.full_config = SimpleNamespace()
    br.config = SimpleNamespace(
        log_level="info",
        holidays=[],
        border_colors=["#FF0000"],
        exclusion_list=exclusion_list or [],
        ignore_folders=[],
        dry_run=False,
        border_width=26,
        border_workers=1,
    )
    return br, dest_dir, by_id


def test_manifest_only_overrides_full_library_triggers(tmp_path, monkeypatch):
    """manifest_only must beat process_all (and any full-library trigger): on
    the plex apply path staged files are transient, so a full sweep would
    re-encode skipped posters into dead temp paths from prior runs. Only the
    manifest item may be written."""
    br, dest_dir, _ = _subset_harness(tmp_path, monkeypatch)

    manifest = {"media_cache": [1], "collections_cache": []}
    br.run(manifest, process_all=True, manifest_only=True)

    assert (dest_dir / "inman.jpg").exists()        # manifest item bordered
    assert not (dest_dir / "outman.jpg").exists()   # full sweep suppressed


def test_excluded_manifest_asset_staged_unbordered(tmp_path, monkeypatch):
    """A border-EXCLUDED manifest asset must still get its raw source staged
    at renamed_file (exclusion means no border, not no poster) — otherwise the
    plex uploader finds nothing to read and fails it on every run."""
    br, dest_dir, by_id = _subset_harness(
        tmp_path, monkeypatch, exclusion_list=["inman"]
    )

    manifest = {"media_cache": [1], "collections_cache": []}
    br.run(manifest, process_all=False)

    dest = dest_dir / "inman.jpg"
    assert dest.exists()
    # Exact source bytes — copied, not bordered.
    with open(by_id[1]["original_file"], "rb") as f:
        src_bytes = f.read()
    assert dest.read_bytes() == src_bytes

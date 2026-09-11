"""Regression tests for the 2026-09 sweep, quality batch."""

import os

import pytest


def _commonpath_reference(child, parent):
    """commonpath-based oracle the nestarr prefix test must agree with."""
    c, p = os.path.normpath(child), os.path.normpath(parent)
    if c == p:
        return False
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False


@pytest.mark.parametrize(
    "child,parent,expected",
    [
        ("/mnt/data/movies/A", "/mnt/data/movies", True),
        ("/mnt/data/movies", "/mnt/data/movies", False),
        ("/mnt/data/movies2/A", "/mnt/data/movies", False),  # sibling prefix trap
        ("/mnt/data/movies/A", "/mnt/data/movies/A/B", False),  # reversed
        ("/mnt/./data/movies/A", "/mnt/data/movies", True),
        ("/mnt/data/movies/../movies/A", "/mnt/data/movies", True),
        ("relative/a", "relative", True),
        ("/absolute/a", "relative", False),
        ("/mnt/x", "/", True),
    ],
)
def test_nesting_matches_the_commonpath_reference(child, parent, expected):
    from backend.modules.nestarr import _NestScanner

    assert _NestScanner._is_nested_path(child, parent) is expected
    assert _commonpath_reference(child, parent) is expected


def test_double_slash_prefix_is_detected():
    """A leading '//' must nest like '/'."""
    from backend.modules.nestarr import _NestScanner

    assert _NestScanner._is_nested_path("//media/data", "//media") is True
    assert _NestScanner._is_nested_path("/mnt/Title (2019)", "//mnt") is True
    # the commonpath oracle misses every leading-'//' parent
    assert _commonpath_reference("//media/data", "//media") is False


def test_normalisation_happens_once_per_path_not_once_per_pair(monkeypatch):
    """The guard against reintroducing normpath inside the O(n^2) loop."""
    from backend.modules import nestarr

    calls = []
    real = os.path.normpath
    monkeypatch.setattr(
        nestarr.os.path, "normpath", lambda p: (calls.append(p), real(p))[1]
    )

    scanner = nestarr._NestScanner.__new__(nestarr._NestScanner)
    media = [_item(f"/mnt/data/movies/T{i}", f"T{i}") for i in range(40)]
    scanner.logger = type("L", (), {"debug": lambda *a, **k: None})()
    scanner._detect_nesting(media, "movie")

    # 40 items => 780 pairs; per-pair normalisation would be >= 1560 calls
    assert len(calls) < 200, f"normpath called {len(calls)} times for 40 items"


def _item(path, title):
    return {
        "path": path,
        "title": title,
        "instance_name": "radarr-main",
        "instance_type": "radarr",
        "media_id": abs(hash(path)) % 10000,
        "root_folder": "/mnt/data/movies",
    }


def _scanner():
    from backend.modules import nestarr

    s = nestarr._NestScanner.__new__(nestarr._NestScanner)
    s.logger = type("L", (), {"debug": lambda *a, **k: None})()
    return s


def test_detect_nesting_still_normalises_messy_paths():
    """Dropping the hoisted normalisation would compare raw strings."""
    media = [
        _item("/mnt/data/movies", "root"),
        _item("/mnt/./data/movies/../movies/Child", "kid"),
    ]
    issues = _scanner()._detect_nesting(media, "movie")
    assert len(issues) == 1, issues


def test_detect_nesting_does_not_flag_a_sibling_prefix():
    """movies2 is not inside movies — the trap a raw prefix test would fall into."""
    media = [
        _item("/mnt/data/movies", "a"),
        _item("/mnt/data/movies2/Title", "b"),
    ]
    assert _scanner()._detect_nesting(media, "movie") == []


def test_owner_filter_does_not_match_sibling_folders(tmp_path):
    """`_` is a LIKE wildcard: `My_Movies` must not match `/drive/MyXMovies`."""
    import sqlite3

    from backend.util.database.db_base import escape_like

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE poster_cache (folder TEXT)")
    db.executemany(
        "INSERT INTO poster_cache VALUES (?)",
        [(f,) for f in ("My_Movies", "/drive/My_Movies", "/drive/MyXMovies")],
    )
    owner = "My_Movies"

    rows = db.execute(
        "SELECT folder FROM poster_cache WHERE (folder = ? OR folder LIKE ? ESCAPE '\\')",
        (owner, f"%/{escape_like(owner)}"),
    ).fetchall()

    assert sorted(r[0] for r in rows) == ["/drive/My_Movies", "My_Movies"]


def test_browse_owner_clause_carries_both_halves():
    """escape_like without the ESCAPE clause silently does nothing."""
    import inspect

    from backend.util.database.poster_cache import PosterCache

    src = inspect.getsource(PosterCache.browse)
    assert "folder LIKE ? ESCAPE" in src
    assert "escape_like(owner)" in src


def test_failed_transcode_leaves_no_temp_file(tmp_path, monkeypatch):
    import glob
    import tempfile
    from unittest import mock

    from PIL import Image

    from backend.util.poster_images import transcode_poster

    src = tmp_path / "p.jpg"
    Image.new("RGB", (20, 20)).save(src)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    before = set(glob.glob(str(tmp_path / "tmp*")))
    with mock.patch.object(Image.Image, "save", side_effect=ValueError("encoder")):
        with pytest.raises(ValueError):
            transcode_poster(str(src), image_format="webp")

    assert set(glob.glob(str(tmp_path / "tmp*"))) == before


def test_successful_transcode_keeps_its_temp_file(tmp_path, monkeypatch):
    """The success path returns the file, so cleanup must not unlink it."""
    import os
    import tempfile

    from PIL import Image

    from backend.util.poster_images import transcode_poster

    src = tmp_path / "p.jpg"
    Image.new("RGB", (20, 20)).save(src)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    path, media_type, ext = transcode_poster(str(src), image_format="webp")
    try:
        assert os.path.exists(path)
        assert media_type == "image/webp"
    finally:
        os.unlink(path)


@pytest.mark.parametrize(
    "size",
    [(9000, 9000), (30000, 30000)],
    ids=["over-our-cap", "over-pillows-bomb-ceiling"],
)
def test_mask_resize_refuses_an_oversized_image(size):
    """Both bands must raise; Pillow's own bomb error must not fall to pass-through."""
    from backend.util.cl2k.limits import ImageTooLargeError
    from backend.util.cl2k.text_removal import _mask_to_image_dims
    from tests.test_cl2k_limits import _png, _undecodable_png

    with pytest.raises(ImageTooLargeError):
        _mask_to_image_dims(_undecodable_png(*size), _png((40, 60)))


class _WarnLog:
    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(msg)


def test_type_error_inside_run_does_not_trigger_a_second_run():
    """A TypeError raised inside run() must propagate, not re-run it without args."""
    from backend.util.job_processor import _run_module_once

    calls = []

    class Module:
        def run(self, only_folders=None, notify=None):
            calls.append({"only_folders": only_folders, "notify": notify})
            raise TypeError("boom inside run")

    log = _WarnLog()
    with pytest.raises(TypeError, match="boom inside run"):
        _run_module_once(Module(), {"only_folders": ["A"], "notify": True}, log, "m")

    assert calls == [{"only_folders": ["A"], "notify": True}]
    assert log.warnings == []


def test_unaccepted_module_args_still_fall_back_to_a_bare_run():
    from backend.util.job_processor import _run_module_once

    calls = []

    class Module:
        def run(self):
            calls.append("bare")

    log = _WarnLog()
    _run_module_once(Module(), {"only_folders": ["A"]}, log, "m")

    assert calls == ["bare"]
    assert len(log.warnings) == 1

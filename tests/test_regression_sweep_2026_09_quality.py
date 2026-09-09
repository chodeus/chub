"""Regression tests for the 2026-09 sweep, quality batch."""

import os

import pytest


# ---------------------------------------------------------------------------
# nestarr nesting predicate: O(n^2) over the media list, so normalise once
# ---------------------------------------------------------------------------


def _commonpath_reference(child, parent):
    """The pre-change implementation, kept as the equivalence oracle."""
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


def test_double_slash_prefix_is_now_detected():
    """commonpath collapses a leading '//', so these nestings were missed."""
    from backend.modules.nestarr import _NestScanner

    assert _NestScanner._is_nested_path("//media/data", "//media") is True
    assert _NestScanner._is_nested_path("/mnt/Title (2019)", "//mnt") is True
    # the old behaviour, recorded so the change is deliberate and visible
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

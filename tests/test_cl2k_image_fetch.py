"""Tests for backend/util/cl2k/image_fetch.py — CL2K render-input selection.

The backdrop selector is resolution-aware: the backdrop fills the whole 1000×1500
poster, so we never want to upscale a soft source when a sharp one exists. The
logo selector is resolution-first by design (a high-voted logo can be low-res).
"""

from backend.util.cl2k import geometry as geo
from backend.util.cl2k.image_fetch import select_backdrop, select_logo


def _bd(path, *, iso=None, h=0, w=0, va=0.0, vc=0):
    return {
        "file_path": path,
        "iso_639_1": iso,
        "height": h,
        "width": w,
        "vote_average": va,
        "vote_count": vc,
    }


def test_backdrop_none_when_empty():
    assert select_backdrop([]) is None


def test_backdrop_prefers_textless_over_language_tagged():
    out = select_backdrop(
        [
            _bd("/en.jpg", iso="en", h=2160, va=9.0),
            _bd("/neutral.jpg", iso=None, h=2160, va=1.0),
        ]
    )
    assert out == "/neutral.jpg"


def test_backdrop_canvas_filling_wins_over_higher_vote_lowres():
    # A 720p backdrop with a great vote must NOT beat a 4K one that fills the
    # canvas — upscaling 720p to 1500px tall would soften the whole poster.
    out = select_backdrop(
        [
            _bd("/hot-but-small.jpg", iso=None, h=720, w=1280, va=9.5, vc=500),
            _bd("/sharp-4k.jpg", iso=None, h=2160, w=3840, va=6.0, vc=10),
        ]
    )
    assert out == "/sharp-4k.jpg"


def test_backdrop_vote_decides_among_canvas_filling():
    # When several fill the canvas, TMDB curation (vote) picks the best.
    out = select_backdrop(
        [
            _bd("/big-meh.jpg", iso=None, h=2160, w=3840, va=5.0, vc=20),
            _bd("/big-great.jpg", iso=None, h=1600, w=2844, va=8.5, vc=40),
        ]
    )
    assert out == "/big-great.jpg"


def test_backdrop_falls_back_to_largest_when_none_fill_canvas():
    out = select_backdrop(
        [
            _bd("/p720.jpg", iso=None, h=720, w=1280, va=9.0),
            _bd("/p1080.jpg", iso=None, h=1080, w=1920, va=1.0),
        ]
    )
    assert out == "/p1080.jpg"


def test_backdrop_threshold_is_canvas_height():
    # Exactly canvas height qualifies as canvas-filling (no upscale needed).
    out = select_backdrop(
        [
            _bd("/exact.jpg", iso=None, h=geo.CANVAS_H, w=2250, va=2.0),
            _bd("/justunder.jpg", iso=None, h=geo.CANVAS_H - 1, w=2250, va=9.0),
        ]
    )
    assert out == "/exact.jpg"


def test_logo_picks_highest_resolution_not_vote():
    out = select_logo(
        [
            {"file_path": "/soft.png", "iso_639_1": "en", "width": 797, "vote_average": 9.0},
            {"file_path": "/sharp.png", "iso_639_1": "en", "width": 2000, "vote_average": 3.0},
        ]
    )
    assert out == "/sharp.png"


def test_strip_and_reinject_plex_token(monkeypatch):
    from types import SimpleNamespace

    from backend.util.cl2k import image_fetch as imf

    url = "http://plex.local:32400/library/metadata/1/thumb/2?X-Plex-Token=SECRET"
    stripped = imf.strip_plex_token(url)
    assert "X-Plex-Token" not in stripped and "SECRET" not in stripped

    cfg = SimpleNamespace(
        instances=SimpleNamespace(
            plex={"p": SimpleNamespace(url="http://plex.local:32400", api="SECRET")}
        )
    )
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    # Re-minted for the matching Plex host…
    assert "X-Plex-Token=SECRET" in imf._with_plex_token(stripped)
    # …but a non-Plex host is left untouched.
    assert (
        imf._with_plex_token("http://image.tmdb.org/x.jpg")
        == "http://image.tmdb.org/x.jpg"
    )

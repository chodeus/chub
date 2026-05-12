"""Unit tests for BorderReplacerr's image-border helpers."""

import pytest
from PIL import Image

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


def test_bundled_borders_dir_exists():
    """Sanity-check that the bundled asset tree shipped with the module."""
    assert _BUNDLED_BORDERS_DIR.is_dir()
    holidays = {p.name for p in _BUNDLED_BORDERS_DIR.iterdir() if p.is_dir()}
    # Spot-check a handful — full inventory is enforced by the rasterize
    # script + Dockerfile, not the test.
    assert {"christmas", "halloween", "pride"}.issubset(holidays)

"""Tests for the CL2K decode caps (Pillow megapixel ceiling + ImageMagick limits).

The bomb fixture is a hand-built PNG: a valid IHDR declaring huge dimensions
followed by a garbage IDAT. Pillow can read its size but not its pixels, so a
test that passes proves the rejection happened from the header, before decode.
"""

import io
import struct
import zlib

import pytest
from PIL import Image

from backend.util.cl2k.limits import (
    MAX_MEGAPIXELS,
    ImageTooLargeError,
    apply_magick_limits,
    open_bounded,
)


def _chunk(kind: bytes, data: bytes) -> bytes:
    """One length-prefixed, CRC-suffixed PNG chunk."""
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def _undecodable_png(width: int, height: int) -> bytes:
    """PNG bytes with a real IHDR of ``width``x``height`` and an unusable IDAT."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", b"\x00" * 8)


def _png(size, color=(20, 30, 40)) -> bytes:
    """A real, decodable PNG of ``size``."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


# 81 MP: over our ceiling, but low enough that Pillow's own guard says nothing at
# all — the band every CL2K decode used to walk straight into.
_BOMB = (9000, 9000)


def test_header_dimensions_reject_a_bomb_before_decoding_it():
    """A bomb is rejected from the IHDR alone — its pixels can't even decode."""
    data = _undecodable_png(*_BOMB)
    header_size = Image.open(io.BytesIO(data)).size
    assert header_size == _BOMB  # header parses, pixels don't
    with pytest.raises(ImageTooLargeError):
        open_bounded(data, "RGB")


def test_the_ceiling_sits_well_under_pillows_own_bomb_threshold():
    """Our ceiling must engage in the band where Pillow stays silent."""
    assert MAX_MEGAPIXELS < Image.MAX_IMAGE_PIXELS / 1_000_000
    assert _BOMB[0] * _BOMB[1] < Image.MAX_IMAGE_PIXELS  # Pillow wouldn't even warn


def test_pillows_own_bomb_error_surfaces_as_ours():
    """DecompressionBombError normalizes to ImageTooLargeError."""
    with pytest.raises(ImageTooLargeError):
        open_bounded(_undecodable_png(30000, 30000), "RGB")


def test_normal_art_decodes_unchanged():
    """Poster-sized art passes through untouched."""
    img = open_bounded(_png((400, 600)), "RGB")
    assert img.size == (400, 600)
    assert img.mode == "RGB"


def test_extraction_entry_points_reject_a_bomb():
    """Every extraction decode site routes through the ceiling."""
    from backend.util.cl2k import logo_extract

    bomb = _undecodable_png(*_BOMB)
    with pytest.raises(ImageTooLargeError):
        logo_extract.extract_title_logo(bomb)
    with pytest.raises(ImageTooLargeError):
        logo_extract._load_mask(bomb, (10, 10))


def test_whiten_helpers_fail_open_on_a_bomb():
    """Whiten helpers keep their fail-open contract on oversized input."""
    # These run mid-render, where the documented contract is "return the input
    # unchanged on any decode failure" — the ceiling must not break that.
    from backend.util.cl2k import logo_extract

    bomb = _undecodable_png(*_BOMB)
    good = _png((40, 40))
    assert logo_extract.ink_color_edges(good, bomb) == good
    assert logo_extract.fill_dark_bodies(good, bomb) == good
    assert logo_extract.flatten_3d_logo(bomb) is None


@pytest.fixture
def magick_limits():
    """ImageMagick's global limits mapping, restored after the test."""
    pytest.importorskip("wand.image")
    from wand.resource import limits

    saved = {k: limits[k] for k in ("memory", "map", "area", "disk", "width", "height")}
    yield limits
    for k, v in saved.items():
        limits[k] = v


def test_apply_magick_limits_caps_the_process(magick_limits):
    """apply_magick_limits writes the wand resource caps."""
    for key in ("memory", "map", "area", "disk", "width", "height"):
        magick_limits[key] = 2**60
    apply_magick_limits()
    for key in ("memory", "map", "area", "disk", "width", "height"):
        assert magick_limits[key] < 2**60


def test_magick_limits_actually_stop_an_oversized_image(magick_limits):
    """Wand raises once an image exceeds the applied caps."""
    from wand.exceptions import WandException
    from wand.image import Image as WandImage

    data = _png((512, 512))
    with WandImage(blob=data) as ok:
        assert ok.size == (512, 512)  # decodes fine under the shipped caps
    magick_limits["width"] = 64
    magick_limits["height"] = 64
    with pytest.raises(WandException):
        with WandImage(blob=data):
            pass

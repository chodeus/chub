"""Tests for the 3D/extruded logo mode (keep the lit face, drop the extrusion).

The two-tone whiten speckles a gloss gradient black and the flat silhouette fuses
each letter with the extrusion joining it to its neighbour, so this mode has to do
something neither does: split face from extrusion. It must also refuse politely —
a logo it can't split falls back to the flat silhouette, never to the two-tone.
"""

import io

import numpy as np
import pytest
from PIL import Image as PILImage

from backend.util.cl2k.logo_extract import flatten_3d_logo


def _png(arr):
    """
    Encode an RGBA array as PNG bytes.
    
    Parameters:
    	arr (numpy.ndarray): RGBA pixel data to encode.
    
    Returns:
    	bytes: PNG-encoded image data.
    """
    buf = io.BytesIO()
    PILImage.fromarray(arr, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def _extruded(face=235, side=110, size=80):
    """Two bright square 'letters' over a darker offset extrusion, on transparency."""
    a = np.zeros((size, size, 4), dtype=np.uint8)
    for x0 in (10, 46):
        a[24:64, x0 + 6 : x0 + 30] = (side, side, side, 255)  # extrusion, down-right
        a[18:58, x0 : x0 + 24] = (face, face, face, 255)  # lit face
    return a


def test_face_is_kept_and_the_extrusion_is_dropped():
    src = _extruded()
    out = flatten_3d_logo(_png(src))
    assert out is not None
    res = np.asarray(PILImage.open(io.BytesIO(out)).convert("RGBA"))
    alpha = res[..., 3]
    face = src[..., 0] > 200
    extrusion_only = (src[..., 0] > 50) & (src[..., 0] < 200)
    assert alpha[face].mean() > 200, "the lit face must survive"
    assert alpha[extrusion_only].mean() < 40, "the extrusion must be dropped"


def test_kept_pixels_are_pure_white():
    out = flatten_3d_logo(_png(_extruded()))
    res = np.asarray(PILImage.open(io.BytesIO(out)).convert("RGBA"))
    assert (res[..., :3][res[..., 3] > 128] == 255).all()


def test_a_flat_logo_is_refused_rather_than_hollowed_out():
    """One uniform colour has no face/extrusion split — the caller must fall back."""
    a = np.zeros((80, 80, 4), dtype=np.uint8)
    a[20:60, 20:60] = (200, 200, 200, 255)
    assert flatten_3d_logo(_png(a)) is None


def test_a_fully_transparent_logo_is_refused():
    assert flatten_3d_logo(_png(np.zeros((40, 40, 4), dtype=np.uint8))) is None


def test_undecodable_bytes_are_refused_not_raised():
    assert flatten_3d_logo(b"not a png") is None


def _long_shadow(h=300, w=900):
    """Face top-left, extrusion and a long shadow trailing far down-right."""
    a = np.zeros((h, w, 4), dtype=np.uint8)
    a[120:260, 120:760] = (70, 70, 70, 255)
    a[60:200, 60:700] = (150, 150, 150, 255)
    a[20:160, 20:660] = (245, 245, 245, 255)
    return a


def test_process_logo_retrims_the_freed_extrusion_padding():
    """Dropping the extrusion frees padding _place_logo would otherwise size and
    bottom-align by — the returned box must be the FACE's box, edge to edge."""
    pytest.importorskip("wand.image")
    from backend.util.cl2k.renderer import process_logo

    src = _png(_long_shadow())
    blob, w, h = process_logo(src, whiten=True, logo_3d=True)
    res = PILImage.open(io.BytesIO(blob)).convert("RGBA")
    assert (w, h) == res.size
    bbox = res.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    assert bbox == (0, 0, w, h), f"transparent margin left around the face: {bbox} in {w}x{h}"
    # A trimmed box alone would also pass on the flat-white fallback, which keeps
    # the whole silhouette — so require that the extrusion actually went.
    _flat, fw, fh = process_logo(src, whiten=True, flat_white=True)
    assert w < fw and h < fh, f"face box {w}x{h} not smaller than the silhouette {fw}x{fh}"


@pytest.mark.parametrize("mode", ["logo_3d", "flat_white"])
def test_process_logo_modes_produce_a_white_only_logo(mode):
    """logo_3d must rank above flat_white, and both must leave RGB pure white."""
    pytest.importorskip("wand.image")
    from backend.util.cl2k.renderer import process_logo

    kwargs = {"whiten": True, "flat_white": True}
    if mode == "logo_3d":
        kwargs["logo_3d"] = True
    blob, _w, _h = process_logo(_png(_extruded()), **kwargs)
    res = np.asarray(PILImage.open(io.BytesIO(blob)).convert("RGBA"))
    opaque = res[..., 3] > 128
    assert opaque.any()
    assert (res[..., :3][opaque] == 255).all()
    # The face-only pass must keep strictly less than the whole silhouette.
    if mode == "logo_3d":
        assert opaque.sum() < (np.asarray(_extruded())[..., 3] > 128).sum()

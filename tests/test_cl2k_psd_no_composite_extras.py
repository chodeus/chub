"""PSD export must not need psd-tools' [composite] extra, which the image no longer ships.
Doubles as a layer-presence guard: every expected layer must survive the export.
"""

import builtins
import io

import pytest
from PIL import Image, ImageDraw
from psd_tools import PSDImage
from psd_tools.constants import Tag

# scipy / scikit-image (+ their deps) arrive only with psd-tools[composite] and back
# PSDImage.composite(); psd_live builds its own preview instead. See requirements-cl2k.txt.
COMPOSITE_EXTRAS = {"scipy", "skimage", "aggdraw", "networkx", "tifffile", "imageio"}


@pytest.fixture
def no_composite_extras(monkeypatch):
    """Make every [composite]-only package unimportable for the duration of a test."""
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in COMPOSITE_EXTRAS:
            raise ImportError(f"{name} is not installed (psd-tools[composite] extra)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)


def _png(width, height, fill, band=False):
    """Deterministic PNG bytes; band=True paints an opaque bar so a logo has ink."""
    im = Image.new("RGBA", (width, height), fill)
    if band:
        ImageDraw.Draw(im).rectangle(
            [width // 8, height // 3, width * 7 // 8, height * 2 // 3],
            fill=(255, 255, 255, 255),
        )
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _layer_names(blob):
    """Top-level layer names of a PSD blob, in document order."""
    return [layer.name for layer in PSDImage.open(io.BytesIO(blob))]


def _find(blob, name):
    return next(
        (ly for ly in PSDImage.open(io.BytesIO(blob)) if ly.name == name), None
    )


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"kind": "movie", "title": "Probe"}, ["POSTER", "GRADIENT", "LOGO", "BORDER LAYER"]),
        (
            {"kind": "collection", "title": "Best Of"},
            ["POSTER", "GRADIENT", "LOGO", "COLLECTION", "BORDER LAYER"],
        ),
        (
            {"kind": "season", "title": "Show", "season_text": "Season 3"},
            ["POSTER", "GRADIENT", "LOGO", "SEASON 3", "BORDER LAYER"],
        ),
        (
            {"kind": "season", "title": "Show", "band_label": "Complete Limited Series"},
            ["POSTER", "GRADIENT", "LOGO", "COMPLETE LIMITED SERIES", "BORDER LAYER"],
        ),
    ],
)
def test_export_keeps_every_layer_without_the_composite_extras(
    no_composite_extras, kwargs, expected
):
    """Each export variant ships its full layer stack with the extras unimportable."""
    from backend.util.cl2k.psd_export import export_psd

    blob = export_psd(
        backdrop_bytes=_png(1600, 900, (40, 70, 120)),
        logo_bytes=_png(800, 300, (0, 0, 0, 0), band=True),
        **kwargs,
    )
    names = _layer_names(blob)
    assert names == expected


def test_live_layers_survive_without_the_composite_extras(no_composite_extras):
    """The gradient fill stays live and the label stays an editable type layer."""
    from backend.util.cl2k.psd_export import export_psd

    blob = export_psd(
        backdrop_bytes=_png(1600, 900, (40, 70, 120)),
        logo_bytes=_png(800, 300, (0, 0, 0, 0), band=True),
        kind="season",
        title="Show",
        season_text="Season 3",
    )
    gradient = _find(blob, "GRADIENT")
    assert gradient is not None and gradient[0].kind == "gradientfill"

    label = _find(blob, "SEASON 3")
    assert label is not None and label.kind == "type"
    assert Tag.TYPE_TOOL_OBJECT_SETTING in label.tagged_blocks

    # Reopened outside the assert: -O strips assert bodies, taking the call with it.
    reopened = PSDImage.open(io.BytesIO(blob))
    assert reopened.has_preview()


def test_the_extras_guard_actually_bites(no_composite_extras):
    """Known-answer control: without this failing, the tests above prove nothing."""
    with pytest.raises(ImportError):
        __import__("scipy")

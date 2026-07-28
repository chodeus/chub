"""Extract the CL2K label type-layer donor -> backend/assets/cl2k/label_tysh.bin.

A live (editable) text layer needs a full Photoshop ``TySh`` block, most of
which is the text engine's serialized state (``EngineData``): stock kinsoku /
mojikumi tables, style and paragraph sheets, the font set. Hand-building that
structure risks a file Photoshop refuses to open, so the export transplants a
donor block instead and rewrites the string/tracking/anchor per poster
(see backend/util/cl2k/psd_live.py:label_type_block).

This script produces that donor from a finished creator PSD's label layer,
neutralised: the text becomes the placeholder ``LABEL`` and the anchor is
zeroed. What remains is the text-engine boilerplate plus the CL2K label
typography facts already recorded in geometry.py (ArialMT, 32px, white,
centre-justified, tracking 800) — the same derive-locally-commit-derivative
pattern as gen_cl2k_gradient.py and gen_cl2k_inner_glow.py.

Needs a creator PSD under refs/, which is gitignored (copyrighted, local
only). The generated .bin is committed; re-run only if the template changes.

Run from the repo root:
    PYTHONPATH=. .venv/bin/python scripts/gen_cl2k_label_tysh.py [path/to.psd]
"""

import copy
import io
import sys
from pathlib import Path

from psd_tools import PSDImage
from psd_tools.constants import Tag
from psd_tools.psd.tagged_blocks import TaggedBlock

OUT = Path("backend/assets/cl2k/label_tysh.bin")
DEFAULT_SRC = "refs/Zero Day (2025) {tmdb-216082} {tvdb-431842} {imdb-tt23872886}.psd"
DONOR_LAYER = "SPECIALS"
PLACEHOLDER = "LABEL"


def _find(layers, name):
    for layer in layers:
        if layer.name == name:
            return layer
        if layer.is_group():
            hit = _find(layer, name)
            if hit:
                return hit
    return None


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    psd = PSDImage.open(src)
    donor = _find(psd, DONOR_LAYER)
    if donor is None or donor.kind != "type":
        raise SystemExit(f"no type layer named {DONOR_LAYER!r} in {src}")

    block = copy.deepcopy(donor._record.tagged_blocks[Tag.TYPE_TOOL_OBJECT_SETTING])
    tysh = block.data
    tysh.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    td = tysh.text_data
    td[b"Txt "].value = PLACEHOLDER + "\x00"
    engine = td[b"EngineData"].value["EngineDict"]
    engine["Editor"]["Text"].value = PLACEHOLDER + "\r"
    for run in ("StyleRun", "ParagraphRun"):
        lengths = engine[run]["RunLengthArray"]
        item = copy.deepcopy(lengths[0])
        item.value = len(PLACEHOLDER) + 1
        lengths._items[:] = [item]

    buf = io.BytesIO()
    block.write(buf, version=1, padding=1)
    data = buf.getvalue()

    # Round-trip proof before committing bytes to disk.
    reread = TaggedBlock.read(io.BytesIO(data), version=1, padding=1)
    text = reread.data.text_data[b"Txt "].value.rstrip("\x00")
    assert text == PLACEHOLDER, f"round-trip text {text!r}"

    OUT.write_bytes(data)
    print(f"{OUT} written: {len(data)} bytes, text {text!r}")


if __name__ == "__main__":
    main()

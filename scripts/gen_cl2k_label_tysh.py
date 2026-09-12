"""Extract a neutral CL2K label TySh donor -> backend/assets/cl2k/label_tysh.bin."""

# Run from repo root: PYTHONPATH=. python scripts/gen_cl2k_label_tysh.py [path/to.psd]

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
            if hit is not None:
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

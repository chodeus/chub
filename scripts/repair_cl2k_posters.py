"""Repair the frame on CL2K posters that were generated before the border fix.

WHAT THIS FIXES
    Posters rendered before 2026-07-28 got a frame that was 27px on the top and
    left but 26px on the bottom and right (ImageMagick's rectangle primitive is
    inclusive of both corners, so width=26 painted 27 pixels; only the far edges
    clipped the extra one). When a border-strip pass then cropped a symmetric
    26px, one white column and one white row survived — the thin white line down
    the left edge. Either way the black Inner Glow was never drawn at all.

    Two populations need different treatment, so the mode is chosen per file:

    reframe  The poster still carries its old 27/26 frame (the CL2K maker's own
             output directory, and the Drive copies). The stray frame is cropped
             off using the measured per-edge widths, the surviving artwork is
             resized to the template's 950x1450 inner rect, and the real BORDER
             LAYER is painted over it. Costs a 0.3% resample.
    overlay  The frame has already been stripped and the art re-stretched to fill
             the canvas (the copies Plex serves). The BORDER LAYER is painted
             straight on, which also covers the leftover white line since it sits
             inside the 25px band.

WHAT THIS CANNOT FIX — regenerate the poster instead
    * The black gradient. The old ramp started at y=780 instead of the template's
      y=1038, and it is baked into the pixels. Undoing it means dividing by
      (1 - alpha), which amplifies JPEG noise ~2x by y=1100 and ~8x by y=1350 —
      it would visibly wreck the lower third rather than repair it.
    * The 1.83% horizontal stretch and the q75 / 4:2:0 re-encode that a border
      strip pass applies (it crops to 948x1448 and resizes back to canvas).
      Resolution already lost cannot be recovered by re-encoding.
    So this is a frame repair, not a restoration. It makes existing posters
    correct at the edges; only a re-render makes them correct throughout.

Output is re-encoded at the CL2K settings (q99, 4:4:4, progressive, sRGB) via the
renderer's own encoder, so a repaired file matches a freshly rendered one.

Dry run by default — nothing is written until you pass --apply.

    PYTHONPATH=. python scripts/repair_cl2k_posters.py /path/to/posters
    PYTHONPATH=. python scripts/repair_cl2k_posters.py /path/to/posters --apply
"""

import argparse
import datetime
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image as PILImage
from wand.color import Color
from wand.image import Image as WandImage

from backend.util.cl2k import geometry as geo
from backend.util.cl2k.renderer import _draw_border, _encode_jpeg

# Stamped into the JPEG comment so a second pass can tell what it has already
# touched; without it a repaired poster looks identical to a correct one.
STAMP = "cl2k-repair-v1"
SUFFIXES = (".jpg", ".jpeg")
WHITE = 250  # a JPEG-compressed pure-white border lands a little under 255


def _edge_runs(path: Path) -> Tuple[Tuple[int, int, int, int], Tuple[int, int]]:
    """Return ((left, right, top, bottom) white-run widths, (w, h))."""
    with PILImage.open(path) as im:
        a = np.asarray(im.convert("L")).astype(int)
    h, w = a.shape

    def run(vals: np.ndarray) -> int:
        n = 0
        for v in vals:
            if v < WHITE:
                break
            n += 1
        return n

    # Sample a mid row/column, away from the rounded-looking corner blend.
    row, col = a[h // 2, :], a[:, w // 2]
    return (run(row), run(row[::-1]), run(col), run(col[::-1])), (w, h)


def _stamped(path: Path) -> bool:
    with PILImage.open(path) as im:
        return STAMP in (im.info.get("comment") or b"").decode("utf-8", "replace")


# An old frame measures 26 or 27 per edge; allow a little slack for JPEG ringing
# on a poster whose artwork happens to be near-white right against the frame.
OLD_FRAME_RANGE = (20, 32)
RESIDUE_MAX = 3  # a stripped poster keeps at most the 1px line (+ JPEG bleed)


def _mode_for(runs: Tuple[int, int, int, int]) -> Optional[str]:
    if max(runs) <= RESIDUE_MAX:
        return "overlay"
    if all(OLD_FRAME_RANGE[0] <= r <= OLD_FRAME_RANGE[1] for r in runs):
        return "reframe"
    return None


def repair(path: Path, root: Path, backup_dir: Optional[Path], apply: bool) -> str:
    """Repaint the CL2K frame on one poster. Returns a one-word outcome."""
    runs, size = _edge_runs(path)
    if size != (geo.CANVAS_W, geo.CANVAS_H):
        return f"skip:size={size[0]}x{size[1]}"
    if _stamped(path):
        return "skip:already-repaired"
    mode = _mode_for(runs)
    if mode is None:
        return f"skip:unrecognised-frame={runs}"

    if not apply:
        return f"would-{mode}:edges={runs}"

    if backup_dir is not None:
        # Mirror the tree under the backup root, NOT a flat dump of basenames:
        # a Kometa assets tree repeats `poster.jpg` and `Season01.jpg` in every
        # show folder, so a flat copy would collapse every backup onto one file
        # and leave the originals unrecoverable.
        try:
            rel = path.relative_to(root) if root.is_dir() else Path(path.name)
        except ValueError:
            rel = Path(path.name)
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    bw = geo.BORDER_WIDTH
    with WandImage(filename=str(path)) as img:
        if mode == "reframe":
            left, right, top, bottom = runs
            img.crop(
                left=left,
                top=top,
                width=geo.CANVAS_W - left - right,
                height=geo.CANVAS_H - top - bottom,
            )
            img.resize(geo.CANVAS_W - 2 * bw, geo.CANVAS_H - 2 * bw, filter="lanczos")
            canvas = WandImage(
                width=geo.CANVAS_W, height=geo.CANVAS_H, background=Color(geo.BORDER_COLOR)
            )
            canvas.composite(img, left=bw, top=bw)
        else:
            canvas = img.clone()
        with canvas:
            _draw_border(canvas)
            canvas.metadata["comment"] = STAMP
            blob = _encode_jpeg(canvas)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)  # atomic: never leave a half-written poster behind
    return mode


def _targets(root: Path, exclude: Optional[Path] = None) -> List[Path]:
    """Posters under ``root``, skipping anything inside ``exclude``.

    The backup root is excluded so a second run doesn't pick up the copies it
    made on the first one — which would otherwise re-repair (and re-back-up)
    already-saved originals when the backup dir sits inside the target tree.
    """
    if root.is_file():
        return [root]
    skip = exclude.resolve() if exclude else None

    def outside(p: Path) -> bool:
        if skip is None:
            return True
        try:
            p.resolve().relative_to(skip)
        except ValueError:
            return True
        return False

    return sorted(
        p for p in root.rglob("*") if p.suffix.lower() in SUFFIXES and outside(p)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", type=Path, help="poster file or directory (recursive)")
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--backup-dir", type=Path, help="where originals are copied")
    ap.add_argument("--no-backup", action="store_true", help="do not keep originals")
    ap.add_argument("--limit", type=int, help="only process the first N posters")
    args = ap.parse_args()

    if not args.target.exists():
        raise SystemExit(f"no such path: {args.target}")

    backup_dir: Optional[Path] = None
    if args.apply and not args.no_backup:
        stamp = datetime.date.today().strftime("%Y%m%d")
        base = args.target if args.target.is_dir() else args.target.parent
        backup_dir = args.backup_dir or base.parent / f".cl2k-repair-backups/{stamp}"

    targets = _targets(args.target, backup_dir)
    if args.limit is not None:
        # `if args.limit:` treated 0 as "no limit" and quietly processed the whole
        # tree, and a negative value sliced off all but the last poster. With
        # --apply either is an unintended bulk rewrite.
        if args.limit <= 0:
            ap.error("--limit must be a positive integer")
        targets = targets[: args.limit]
    if not targets:
        raise SystemExit(f"no {'/'.join(SUFFIXES)} files under {args.target}")

    tally: dict = {}
    for path in targets:
        try:
            outcome = repair(path, args.target, backup_dir, args.apply)
        except Exception as exc:  # one bad file must not abandon the batch
            outcome = f"error:{type(exc).__name__}"
            print(f"  !! {path.name}: {exc}", file=sys.stderr)
        tally[outcome.split(":")[0]] = tally.get(outcome.split(":")[0], 0) + 1
        print(f"{outcome:32s} {path.name}")

    print(f"\n{len(targets)} poster(s): " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply.")
    elif backup_dir is not None:
        print(f"originals copied to {backup_dir}")


if __name__ == "__main__":
    main()

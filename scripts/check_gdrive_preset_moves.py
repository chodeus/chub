#!/usr/bin/env python3
"""Fail if a drive id left gdrive_presets.json without a gdrive_preset_moves.json record.

Editing the catalogue alone only ever reaches NEW picks — an existing config
keeps the dropped id forever. The move record is what heals it at config load.

    python3 scripts/check_gdrive_preset_moves.py [--base origin/main]

A replacement id is optional: use "to": null when the owner hasn't supplied one
yet, and fill it in later. Any id put in "to" must be measured live first (an
unshared or emptied folder syncs nothing and reports no error).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS = "backend/assets/gdrive_presets.json"
MOVES = "backend/assets/gdrive_preset_moves.json"


def _ids(blob: str) -> dict:
    return {row["id"]: row.get("name", "?") for row in json.loads(blob)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main", help="ref to compare against")
    args = ap.parse_args()

    try:
        before = _ids(
            subprocess.run(
                ["git", "show", f"{args.base}:{PRESETS}"],
                capture_output=True,
                text=True,
                check=True,
                cwd=ROOT,
            ).stdout
        )
    except subprocess.CalledProcessError:
        # Never pass silently on a missing ref — a skipped check reads as a
        # green check that proves nothing. CI must fetch full history.
        print(
            f"::error::cannot read {PRESETS} at '{args.base}'. "
            "The job needs actions/checkout with fetch-depth: 0.",
            file=sys.stderr,
        )
        return 2

    after = _ids((ROOT / PRESETS).read_text(encoding="utf-8"))
    moves = json.loads((ROOT / MOVES).read_text(encoding="utf-8"))
    recorded = {row["from"] for row in moves if row.get("from")}

    failures = []
    for dropped in set(before) - set(after):
        if dropped not in recorded:
            failures.append(
                f"{PRESETS}: drive '{before[dropped]}' ({dropped}) was removed or "
                f"had its id changed, but {MOVES} has no record for it. Existing "
                f'configs keep the dead id. Add {{"from": "{dropped}", "to": '
                f'"<new id, or null>", "note": "..."}}.'
            )

    # A replacement must exist in the catalogue, or the heal moves users onto a
    # drive that isn't shipped.
    for row in moves:
        target = row.get("to")
        if target is not None and target not in after:
            failures.append(
                f"{MOVES}: '{row['from']}' heals to '{target}', which is not in "
                f"{PRESETS}."
            )

    for line in failures:
        print(f"::error::{line}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} problem(s) found.", file=sys.stderr)
        return 1

    print(f"OK: {len(before)} -> {len(after)} presets, every dropped id recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

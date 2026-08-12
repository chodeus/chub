"""Assert every tracked JSON asset parses, and the release manifest is well-formed."""

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# package-lock.json is generated + huge; `npm ci` already validates it.
EXCLUDED = {"frontend/package-lock.json"}


def _tracked_json_files():
    """Return repo-relative paths of every git-tracked *.json outside EXCLUDED."""
    out = subprocess.check_output(
        ["git", "ls-files", "*.json"], cwd=REPO_ROOT, text=True
    )
    return [p for p in out.splitlines() if p and p not in EXCLUDED]


def test_all_tracked_json_assets_parse():
    """Every tracked JSON asset must be valid JSON."""
    failures = []
    for rel in _tracked_json_files():
        try:
            json.loads((REPO_ROOT / rel).read_text())
        except (json.JSONDecodeError, OSError) as exc:
            failures.append(f"{rel}: {exc}")
    assert not failures, "Invalid JSON asset(s):\n" + "\n".join(failures)


def test_release_manifest_is_stable_base_semver():
    """Manifest '.' is the X.Y.Z base backend/util/version.py appends branch/build to."""
    manifest = json.loads((REPO_ROOT / ".release-please-manifest.json").read_text())
    assert "." in manifest, "manifest missing '.' key"
    # ASCII, no leading zeros; version.py splits this as the 3-component base.
    semver = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    assert re.fullmatch(semver, manifest["."].strip()), manifest["."]

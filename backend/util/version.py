import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import requests

MANIFEST = Path(__file__).parents[2] / ".release-please-manifest.json"


def _read_base_version() -> str:
    """Read the current version from the release-please manifest."""
    return json.loads(MANIFEST.read_text())["."].strip()


def get_version() -> str:
    """Get the version string based on environment variables or git information."""
    base_version = _read_base_version()
    ci_build = os.getenv("BUILD_NUMBER")
    ci_branch = os.getenv("BRANCH")
    if ci_build and ci_branch:
        return f"{base_version}.{ci_branch}{ci_build}"

    try:
        branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        commit_count = (
            subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        return f"{base_version}.{branch}{commit_count}"
    except Exception:
        return base_version


# ----- what is actually published -------------------------------------------
GHCR_IMAGE = "chodeus/chub"
_GHCR_ACCEPT = ",".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    )
)


def _image_tag() -> str:
    """Rolling tag this container tracks: :full when the extensions are baked in."""
    return "full" if os.getenv("CHUB_IMAGE_FLAVOR") == "full" else "latest"


def _published_build(logger, tag: str | None = None) -> int | None:
    """BUILD_NUMBER of the newest published image, or None if unknown.

    Every failure returns None, so an unreachable registry never raises a badge.
    """
    tag = tag or _image_tag()
    try:
        tok = requests.get(
            f"https://ghcr.io/token?scope=repository:{GHCR_IMAGE}:pull&service=ghcr.io",
            timeout=5,
        )
        if not tok.ok:
            logger.debug(f"GHCR token failed: {tok.status_code}")
            return None
        head = {
            "Authorization": f"Bearer {tok.json()['token']}",
            "Accept": _GHCR_ACCEPT,
        }
        man = requests.get(
            f"https://ghcr.io/v2/{GHCR_IMAGE}/manifests/{tag}", headers=head, timeout=5
        )
        if not man.ok:
            logger.debug(f"GHCR manifest {tag} failed: {man.status_code}")
            return None
        doc = man.json()
        if "manifests" in doc:  # multi-arch index; BUILD_NUMBER is per-build, not per-arch
            children = [
                m
                for m in doc["manifests"]
                if m.get("platform", {}).get("architecture") not in (None, "unknown")
            ]
            if not children:
                return None
            man = requests.get(
                f"https://ghcr.io/v2/{GHCR_IMAGE}/manifests/{children[0]['digest']}",
                headers=head,
                timeout=5,
            )
            if not man.ok:
                logger.debug(f"GHCR child manifest failed: {man.status_code}")
                return None
            doc = man.json()
        blob = requests.get(
            f"https://ghcr.io/v2/{GHCR_IMAGE}/blobs/{doc['config']['digest']}",
            headers=head,
            timeout=5,
        )
        if not blob.ok:
            logger.debug(f"GHCR config blob failed: {blob.status_code}")
            return None
        for entry in blob.json().get("config", {}).get("Env", []):
            if entry.startswith("BUILD_NUMBER="):
                return int(entry.split("=", 1)[1])
        return None
    except Exception as exc:
        logger.debug(f"Exception reading the published image: {exc}")
        return None


def _check_remote_version(local_version, branch, logger):

    raw_url = f"https://raw.githubusercontent.com/chodeus/chub/{branch}/.release-please-manifest.json"
    try:
        remote_manifest = requests.get(raw_url, timeout=5)
        if not remote_manifest.ok:
            logger.debug(
                f"Could not fetch remote manifest: {remote_manifest.status_code}"
            )
            return None, None, False
        remote_version_str = json.loads(remote_manifest.text)["."].strip()
    except Exception as e:
        logger.debug(f"Exception fetching manifest: {e}")
        return None, None, False

    build_count = _published_build(logger)
    if build_count is None:
        return remote_version_str, None, False

    remote_full = f"{remote_version_str}.{branch}{build_count}"

    update_available = False
    local_parts = local_version.strip().split(".")
    if len(local_parts) >= 4:
        local_base = ".".join(local_parts[:3])
        local_branch_build = local_parts[3]
        m = re.match(r"([a-zA-Z]+)(\d+)", local_branch_build)
        if m:
            local_branch = m.group(1)
            local_build = int(m.group(2))
        else:
            local_branch = local_branch_build.rstrip("0123456789")
            local_build = int(local_branch_build[len(local_branch) :] or 0)
        if remote_version_str == local_base and build_count > local_build:
            update_available = True
        elif remote_version_str != local_base:
            update_available = True
    return remote_full, build_count, update_available


def check_for_update(logger) -> dict:
    """On-demand update check used by GET /api/version/check.

    Derives the branch from the local version, polls the remote manifest +
    commit count via `_check_remote_version`, and returns a summary the UI can
    render. Network failures degrade to `update_available=False` with whatever
    we managed to resolve (never raises).
    """
    local_version = get_version()
    local_parts = local_version.strip().split(".")
    branch = "main"
    if len(local_parts) >= 4:
        m = re.match(r"([a-zA-Z]+)", local_parts[3])
        if m:
            branch = m.group(1)

    remote_full, build_count, update_available = _check_remote_version(
        local_version, branch, logger
    )
    return {
        "local_version": local_version,
        "remote_version": remote_full,
        "branch": branch,
        "build_count": build_count,
        "update_available": bool(update_available),
        "checked": remote_full is not None,
    }


def start_version_check(config, logger, interval=3600):
    """Starts a background thread to check for version updates."""

    def poll():
        local_version = get_version()
        local_parts = local_version.strip().split(".")
        if len(local_parts) < 4:
            return
        branch_and_build = local_parts[3]
        m = re.match(r"([a-zA-Z]+)", branch_and_build)
        branch = m.group(1) if m else "main"
        logger.info(f"[VERSION CHECK] Local version: {local_version}, branch: {branch}")

        while True:
            remote_full, build_count, update_available = _check_remote_version(
                local_version, branch, logger
            )
            if update_available:
                logger.debug(
                    f"[VERSION CHECK] Update available. Local: {local_version}, Remote: {remote_full}, Build Count: {build_count}"
                )
                output = {
                    "local_version": local_version,
                    "remote_version": remote_full,
                    "color": "FF0000",
                }
                from backend.util.notification import NotificationManager

                config.module_name = "version_check"
                manager = NotificationManager(
                    config, logger, module_name="version_check"
                )
                manager.send_notification(output)
            else:
                logger.debug(
                    f"[VERSION CHECK] No update. Local: {local_version}, Remote: {remote_full}"
                )
            time.sleep(interval)

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()

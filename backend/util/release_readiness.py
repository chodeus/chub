"""Shared release-readiness gate.

A media item is "release-ready" when it could plausibly exist in Plex: it has a
released/aired *arr status and (when known) downloaded content. Items that fail
the gate — unreleased movies (``announced``/``upcoming``/``tba``), deleted
entries, and Radarr movies / Sonarr seasons with no downloaded file — have
nothing in Plex to attach artwork to, so the apply paths should skip them
rather than record them as failures.

Single source of truth shared by the unmatched-assets report gate
(``UnmatchedAssets.should_include``) and the Asset Renamerr apply gate, so the
two can't drift. Poster Renamerr's Plex-upload path intentionally does NOT use
this — it gates on the authoritative ``matched`` flag instead.
"""

from typing import Any, Dict

# *arr statuses for items that aren't yet actionable: no file is expected and
# there's nothing in Plex to attach artwork to.
UNRELEASED_STATUSES = frozenset({"announced", "tba", "upcoming", "deleted"})


def is_release_ready(media: Dict[str, Any]) -> bool:
    """True when an item could plausibly be in Plex.

    Fails on an unreleased *arr status, or on a known-absent file
    (``has_content`` False). ``has_content`` of None falls through to True so
    rows not re-stamped by an ARR sync since the column was added aren't
    dropped — the status check is the only gate for those.
    """
    if media.get("status") in UNRELEASED_STATUSES:
        return False
    has_content = media.get("has_content")
    if has_content is not None and not has_content:
        return False
    return True

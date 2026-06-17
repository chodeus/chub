"""Shared release-readiness gate.

A media item is "release-ready" when it could plausibly exist in Plex: it has
downloaded content, or a released/aired *arr status. Items that fail the gate —
Radarr movies / Sonarr seasons with no downloaded file, and unreleased entries
(``announced``/``upcoming``/``tba``/``deleted``) that aren't already in the
library — have nothing in Plex to attach artwork to, so the apply paths should
skip them rather than record them as failures. An unreleased-status item that
IS in the library (downloaded content present) stays eligible — it has a Plex
entry and can take a poster.

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

    Fails on a known-absent file (``has_content`` False), or on an unreleased
    *arr status *when the item isn't already in the library*. An item that is
    in the library (``has_content`` True) — an early/leaked grab, or a Sonarr
    series still flagged ``upcoming`` with episodes on disk — IS in Plex and
    can take a poster, so it stays eligible even with an unreleased status.

    ``has_content`` of None (row not re-stamped by an ARR sync since the column
    was added) is treated as "not confirmed present": it falls through the
    known-absent check but still triggers the status gate, preserving the
    migration-NULL safety so genuinely-unreleased un-synced rows aren't surfaced.
    """
    has_content = media.get("has_content")
    if has_content is not None and not has_content:
        return False
    if media.get("status") in UNRELEASED_STATUSES and not has_content:
        return False
    return True

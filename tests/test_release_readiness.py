"""Unit tests for the shared release-readiness gate."""

import pytest

from backend.util.release_readiness import UNRELEASED_STATUSES, is_release_ready


@pytest.mark.parametrize("status", sorted(UNRELEASED_STATUSES))
def test_unreleased_status_gated_only_without_content(status):
    # Unreleased/deleted statuses are gated when content is unknown (None) or
    # known-absent — there's nothing in Plex to attach a poster to.
    assert is_release_ready({"status": status, "has_content": None}) is False
    assert is_release_ready({"status": status, "has_content": False}) is False
    # ...but an item already in the library (an early/leaked grab, or a Sonarr
    # series still flagged "upcoming" with episodes on disk) IS in Plex and can
    # take a poster, so it stays eligible despite the unreleased status.
    assert is_release_ready({"status": status, "has_content": True}) is True


def test_undownloaded_is_not_ready():
    # Released but no file (Radarr movie) or no episodes (Sonarr season).
    assert is_release_ready({"status": "released", "has_content": False}) is False
    assert is_release_ready({"status": "continuing", "has_content": 0}) is False


def test_released_with_content_is_ready():
    assert is_release_ready({"status": "released", "has_content": True}) is True
    assert is_release_ready({"status": "continuing", "has_content": 1}) is True
    assert is_release_ready({"status": "ended", "has_content": True}) is True


def test_unknown_has_content_falls_through_to_ready():
    # None has_content (row not re-stamped since the column was added) is NOT a
    # gate on its own — only the status check applies for those rows.
    assert is_release_ready({"status": "released", "has_content": None}) is True
    assert is_release_ready({"status": "released"}) is True


def test_collection_like_row_with_no_fields_is_ready():
    # Collection rows carry no status/has_content; they must not be gated out.
    assert is_release_ready({}) is True

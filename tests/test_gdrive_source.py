"""Tests for backend/util/gdrive_source.py — path -> configured drive resolution.

This is the single owner of "which Google Drive supplied this file". Before it
existed the longest-ancestor rule was spelled out in poster_renamerr and the
drive was guessed elsewhere as ``basename(dirname(file))``, which names the media
folder rather than the drive on a Kometa-style layout.
"""

from types import SimpleNamespace

import pytest

from backend.api.posters._shared import annotate_drive
from backend.util.gdrive_source import (
    build_drive_map,
    resolve_drive_for_path,
    style_of,
)


def entry(name, location):
    return SimpleNamespace(name=name, location=location)


@pytest.fixture
def drive_map(tmp_path):
    """Two drives where one is nested inside the other, to exercise longest-wins."""
    parent = tmp_path / "posters"
    nested = parent / "CL2K" / "Solen"
    nested.mkdir(parents=True)
    return (
        build_drive_map([entry("All Posters", str(parent)), entry("CL2K Solen", str(nested))]),
        parent,
        nested,
    )


def test_longest_location_wins_over_its_parent(drive_map):
    mapping, parent, nested = drive_map
    assert resolve_drive_for_path(str(nested / "Inception (2010).jpg"), mapping) == "CL2K Solen"
    assert resolve_drive_for_path(str(parent / "Loose (1999).jpg"), mapping) == "All Posters"


def test_the_location_itself_resolves(drive_map):
    mapping, _parent, nested = drive_map
    assert resolve_drive_for_path(str(nested), mapping) == "CL2K Solen"


def test_a_path_outside_every_drive_is_unresolved(drive_map, tmp_path):
    mapping, _parent, _nested = drive_map
    local = tmp_path / "local_dir" / "Movie (2020).jpg"
    assert resolve_drive_for_path(str(local), mapping) is None


def test_a_sibling_sharing_a_name_prefix_does_not_match(tmp_path):
    """`/posters/CL2K` must not claim `/posters/CL2K-extra`; the guard is the
    separator, not startswith alone."""
    (tmp_path / "CL2K").mkdir()
    (tmp_path / "CL2K-extra").mkdir()
    mapping = build_drive_map([entry("CL2K Main", str(tmp_path / "CL2K"))])
    assert resolve_drive_for_path(str(tmp_path / "CL2K-extra" / "a.jpg"), mapping) is None


def test_entries_missing_a_name_or_location_are_skipped():
    mapping = build_drive_map(
        [entry("", "/posters/unnamed"), entry("No Location", ""), entry(None, None)]
    )
    assert mapping == {}


def test_an_empty_config_resolves_to_nothing():
    assert build_drive_map(None) == {}
    assert resolve_drive_for_path("/posters/anything.jpg", {}) is None
    assert resolve_drive_for_path("", {"/posters": "X"}) is None


@pytest.mark.parametrize(
    "name, expected",
    [("CL2K Solen", "CL2K"), ("MM2K", "MM2K"), ("  Spaced  Out ", "Spaced"), (None, None), ("", None)],
)
def test_style_is_the_first_word_of_the_drive_name(name, expected):
    assert style_of(name) == expected


def test_annotate_drive_stamps_each_row(monkeypatch, tmp_path):
    nested = tmp_path / "CL2K" / "Solen"
    nested.mkdir(parents=True)
    cfg = SimpleNamespace(
        sync_gdrive=SimpleNamespace(gdrive_list=[entry("CL2K Solen", str(nested))])
    )
    monkeypatch.setattr("backend.api.posters._shared.load_config", lambda: cfg)

    rows = [{"file": str(nested / "a.jpg")}, {"file": "/somewhere/else/b.jpg"}]
    annotate_drive(rows)

    assert rows[0]["drive"] == "CL2K Solen"
    assert rows[1]["drive"] is None


def test_annotate_drive_reports_none_rather_than_failing_when_config_will_not_load(
    monkeypatch,
):
    """Provenance is cosmetic: a broken config must not fail the whole report."""

    def boom():
        raise RuntimeError("config unreadable")

    monkeypatch.setattr("backend.api.posters._shared.load_config", boom)

    rows = [{"file": "/posters/CL2K/Solen/a.jpg"}]
    annotate_drive(rows)

    assert rows[0]["drive"] is None


def test_annotate_drive_tolerates_an_empty_list():
    rows = []
    annotate_drive(rows)
    assert rows == []

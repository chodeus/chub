import json

import pytest

from backend.util import gdrive_presets
from backend.util.config import GDriveListEntry


@pytest.fixture(autouse=True)
def _clear_caches():
    gdrive_presets._presets_cache = None
    gdrive_presets._moves_cache = None
    yield
    gdrive_presets._presets_cache = None
    gdrive_presets._moves_cache = None


def _entry(drive_id, name="MM2K Someone", location="/kometa/posters/MM2K/Someone"):
    return GDriveListEntry(id=drive_id, name=name, location=location)


def test_shipped_moves_and_presets_parse():
    moves = gdrive_presets.load_moves()
    presets = gdrive_presets.load_presets()
    assert moves, "move table should not be empty"
    # A relocation must point at an id the catalogue actually ships, or the heal
    # would move users onto a drive that no longer exists.
    catalogue_ids = {p["id"] for p in presets}
    for old, new in moves.items():
        assert old not in catalogue_ids, f"{old} is retired but still in the catalogue"
        if new is not None:
            assert new in catalogue_ids, f"{old} heals to {new}, absent from catalogue"


def test_relocated_id_is_healed():
    entry = _entry("1HjwMWfI6XpQVYH36VBzYiJA4UWfoqcQ9", name="MM2K IamSpartacus")
    assert gdrive_presets.reconcile_gdrive_list([entry]) == 1
    assert entry.id == "19_kDCSHFdeZypxOxmODWmEt6jtBBtOYw"


def test_retired_id_is_left_alone():
    # Nothing to heal to — warn, but never silently repoint or drop the entry.
    entry = _entry("1cqDinU27cnHf5sL5rSlfO7o_T6LSxG77", name="MM2K Reitenth")
    assert gdrive_presets.reconcile_gdrive_list([entry]) == 0
    assert entry.id == "1cqDinU27cnHf5sL5rSlfO7o_T6LSxG77"


def test_unknown_and_current_ids_untouched():
    custom = _entry("1UserOwnedDriveIdAAAAAAAAAAAAAAAA", name="My own drive")
    live = _entry("19_kDCSHFdeZypxOxmODWmEt6jtBBtOYw", name="MM2K IamSpartacus")
    assert gdrive_presets.reconcile_gdrive_list([custom, live]) == 0
    assert custom.id == "1UserOwnedDriveIdAAAAAAAAAAAAAAAA"
    assert live.id == "19_kDCSHFdeZypxOxmODWmEt6jtBBtOYw"


def test_reconcile_is_idempotent():
    entry = _entry("1HjwMWfI6XpQVYH36VBzYiJA4UWfoqcQ9")
    assert gdrive_presets.reconcile_gdrive_list([entry]) == 1
    assert gdrive_presets.reconcile_gdrive_list([entry]) == 0


def test_location_and_name_are_never_rewritten():
    # location is a live directory sync_gdrive writes into and source_dirs point at.
    entry = _entry(
        "1HjwMWfI6XpQVYH36VBzYiJA4UWfoqcQ9",
        name="MM2K IamSpartacus",
        location="/kometa/posters/MM2K/IamSpartacus",
    )
    gdrive_presets.reconcile_gdrive_list([entry])
    assert entry.location == "/kometa/posters/MM2K/IamSpartacus"
    assert entry.name == "MM2K IamSpartacus"


def test_missing_move_table_fails_open(monkeypatch, tmp_path):
    monkeypatch.setattr(gdrive_presets, "MOVES_PATH", tmp_path / "nope.json")
    entry = _entry("1HjwMWfI6XpQVYH36VBzYiJA4UWfoqcQ9")
    assert gdrive_presets.reconcile_gdrive_list([entry]) == 0
    assert entry.id == "1HjwMWfI6XpQVYH36VBzYiJA4UWfoqcQ9"


def test_empty_and_none_lists_are_safe():
    assert gdrive_presets.reconcile_gdrive_list([]) == 0
    assert gdrive_presets.reconcile_gdrive_list(None) == 0


def test_move_table_shape_is_valid_json():
    rows = json.loads(gdrive_presets.MOVES_PATH.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    for row in rows:
        assert row.get("from"), "every row needs a 'from' id"
        assert "to" in row, "every row needs a 'to' (null = retired)"
        assert row.get("note"), "every row needs a note explaining the move"

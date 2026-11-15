"""backend.util.writable: where a write would land, and whether CHUB can make it."""

from backend.util.writable import nearest_existing_dir, writable_error


def test_a_writable_folder_passes_and_keeps_no_probe_file(tmp_path):
    refusal = writable_error(str(tmp_path / "new" / "deeper"))
    assert refusal is None
    assert list(tmp_path.iterdir()) == []


def test_nearest_existing_dir_climbs_past_missing_folders_and_files(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    assert nearest_existing_dir(str(tmp_path / "a" / "b")) == str(tmp_path)
    assert nearest_existing_dir(str(blocker / "x")) == str(tmp_path)
    assert nearest_existing_dir(str(tmp_path)) == str(tmp_path)

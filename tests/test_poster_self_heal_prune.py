"""Pruning open review rows that can no longer be acted on.

After a heal lands, the row describing it is history: its Apply would fail
forever because the target it wants is already on disk. Left open it sits in the
review queue with no way out except Dismiss.
"""

from backend.modules.poster_self_heal import is_already_healed


def _row(old_path, proposed):
    return {"poster_file": str(old_path), "proposed_filename": proposed}


def test_already_healed_when_old_is_gone_and_proposed_exists(tmp_path):
    new = tmp_path / "Movie (2020) {tmdb-1} {tvdb-2}.jpg"
    new.write_text("x")
    row = _row(tmp_path / "Movie (2020) {tmdb-1}.jpg", new.name)
    assert is_already_healed(row) is True


def test_not_healed_while_the_original_is_still_there(tmp_path):
    old = tmp_path / "Movie (2020) {tmdb-1}.jpg"
    old.write_text("x")
    new = tmp_path / "Movie (2020) {tmdb-1} {tvdb-2}.jpg"
    new.write_text("x")
    assert is_already_healed(_row(old, new.name)) is False


def test_not_healed_when_neither_exists(tmp_path):
    """The unmounted-share guard: everything missing must NOT read as healed, or
    a disconnected mount would prune the entire queue."""
    row = _row(tmp_path / "gone.jpg", "also-gone.jpg")
    assert is_already_healed(row) is False


def test_not_healed_for_a_live_drive_row(tmp_path):
    """Drive-sourced rows carry a bare filename, not an absolute path."""
    assert is_already_healed({"poster_file": "Movie.jpg", "proposed_filename": "New.jpg"}) is False


def test_not_healed_without_a_proposed_name(tmp_path):
    assert is_already_healed(_row(tmp_path / "x.jpg", "")) is False
    assert is_already_healed({"poster_file": str(tmp_path / "x.jpg")}) is False


def test_proposed_is_resolved_beside_the_original(tmp_path):
    """The proposed name is a basename — it must be joined to the OLD row's
    directory, not the process cwd."""
    sub = tmp_path / "CL2K" / "Chodeus"
    sub.mkdir(parents=True)
    new = sub / "Show (2021) {tmdb-9} {tvdb-8}.jpg"
    new.write_text("x")
    row = _row(sub / "Show (2021) {tmdb-9}.jpg", new.name)
    assert is_already_healed(row) is True
    # Same filenames under a different directory must not match.
    other = _row(tmp_path / "elsewhere" / "Show (2021) {tmdb-9}.jpg", new.name)
    assert is_already_healed(other) is False

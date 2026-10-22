"""Folder verdicts and file outcomes renameinatorr checks before and after a rename."""

import pytest

from backend.util.arr import relative_to
from backend.util.rename_checks import (
    BLOCKED,
    HELD,
    KEEP,
    MOVE,
    check_files,
    fold,
    irregular_reasons,
    plan_folder,
    plan_folders,
    records_drifted,
    taken_paths,
    untracked,
)

ROOT = "/data/media/tv"


def _item(folder, media_id=1, root=ROOT):
    return {"media_id": media_id, "path": f"{root}/{folder}", "root_folder": root}


def _verdict(folder, expected, siblings=None, taken=None, item=None):
    item = item or _item(folder)
    siblings = {folder} if siblings is None else siblings
    return plan_folder(item, expected, taken or taken_paths([item]), siblings)


def test_a_folder_already_named_right_stays():
    assert _verdict("Show (2011)", "Show (2011)").action == KEEP


def test_a_plain_rename_moves():
    assert _verdict("Show 2011", "Show (2011)").action == MOVE


def test_a_capitals_only_rename_is_not_a_clash_with_itself():
    assert _verdict("show (2011)", "Show (2011)").action == MOVE


@pytest.mark.parametrize(
    "current, expected, reason",
    [
        ("Show (2011)", "Show", "the new name drops the year 2011"),
        (
            "Show (2011) {tvdb-12345}",
            "Show (2011)",
            "the new name drops the tvdb id 12345",
        ),
        (
            "Show (2011) [imdbid-tt01]",
            "Show (2011)",
            "the new name drops the imdb id tt01",
        ),
        ("Show (2011)", "Show (2011) {tvdb-0}", "the new name has an empty tvdb id"),
        ("Show (2011)", "Show (2011) {tmdb-}", "the new name has an empty tmdb id"),
        ("Show (2011)", "(2011)", "the new name has no title"),
    ],
)
def test_a_rename_that_loses_information_is_held(current, expected, reason):
    verdict = _verdict(current, expected)

    assert verdict.action == HELD
    assert reason in verdict.reason


def test_a_corrected_year_or_id_is_not_irregular():
    assert irregular_reasons("Show (2010) {tvdb-1}", "Show (2011) {tvdb-2}") == []


@pytest.mark.parametrize(
    "expected, why",
    [
        ("", "has no folder name"),
        ("  ", "unusable"),
        ("a/b", "unusable"),
        ("..", "unusable"),
        (None, "couldn't be read"),
    ],
)
def test_an_unusable_or_unread_name_blocks(expected, why):
    verdict = _verdict("Show", expected)

    assert verdict.action == BLOCKED
    assert why in verdict.reason


def test_a_name_another_folder_has_blocks():
    verdict = _verdict("Show", "Show (2011)", siblings={"Show", "show (2011)"})

    assert verdict.action == BLOCKED
    assert "already exists" in verdict.reason


def test_a_capitals_only_rename_onto_a_separate_folder_blocks():
    verdict = _verdict("show", "Show", siblings={"show", "Show"})

    assert verdict.action == BLOCKED


def test_a_name_another_item_uses_blocks():
    other = _item("Show (2011)", media_id=2)
    item = _item("Show")

    verdict = plan_folder(item, "Show (2011)", taken_paths([item, other]), {"Show"})

    assert verdict.action == BLOCKED
    assert "another item" in verdict.reason


def test_a_nested_folder_blocks():
    item = _item("S/Show")

    verdict = plan_folder(item, "Show (2011)", taken_paths([item]), {"S"})

    assert verdict.action == BLOCKED
    assert "subfolder" in verdict.reason


def test_a_trailing_slash_on_the_root_folder_is_not_nesting():
    item = {"media_id": 1, "path": f"{ROOT}/Show", "root_folder": ROOT + "/"}

    assert plan_folder(item, "Show (2011)", set(), {"Show"}).action == MOVE


def test_a_folder_missing_from_disk_blocks():
    verdict = _verdict("Show", "Show (2011)", siblings={"Other"})

    assert verdict.action == BLOCKED
    assert "isn't on disk" in verdict.reason


def test_an_unreadable_listing_blocks():
    item = _item("Show")

    verdict = plan_folder(item, "Show (2011)", set(), None)

    assert verdict.action == BLOCKED
    assert "couldn't be listed" in verdict.reason


def test_two_items_wanting_one_name_only_move_the_first():
    first, second = _item("Show A", 1), _item("Show B", 2)
    listings = {ROOT: {"Show A", "Show B"}}

    verdicts = plan_folders(
        [first, second], {1: "Show", 2: "Show"}, taken_paths([first, second]), listings
    )

    assert verdicts[1].action == MOVE
    assert verdicts[2].action == BLOCKED


def test_a_planned_move_claims_its_path_for_later_batches():
    item = _item("Show A")
    taken = taken_paths([item])

    plan_folders([item], {1: "Show"}, taken, {ROOT: {"Show A"}})

    assert fold(f"{ROOT}/Show") in taken


def test_relative_to_strips_the_folder_and_a_leading_slash():
    assert (
        relative_to("/music/Artist/Album/01.flac", "/music/Artist") == "Album/01.flac"
    )
    assert relative_to("Season 01/x.mkv", "/tv/Show") == "Season 01/x.mkv"
    assert relative_to("/elsewhere/x.flac", "/music/Artist") == "elsewhere/x.flac"


def test_a_clean_rename_is_reported_and_its_record_expected_at_the_new_name():
    outcome = check_files(
        {"a.mkv", "b.mkv"},
        {1: "a.mkv", 2: "b.mkv"},
        {"a.mkv": "A.mkv"},
        {"A.mkv", "b.mkv"},
        set(),
    )

    assert outcome.renamed == {"a.mkv": "A.mkv"}
    assert outcome.missing == []
    assert outcome.expected_records == {1: "A.mkv", 2: "b.mkv"}


def test_a_rename_that_did_not_happen_is_not_reported():
    outcome = check_files({"a.mkv"}, {1: "a.mkv"}, {"a.mkv": "A.mkv"}, {"a.mkv"}, set())

    assert outcome.renamed == {}
    assert outcome.not_renamed == ["a.mkv"]
    assert outcome.missing == []


def test_a_file_gone_under_both_names_is_missing():
    outcome = check_files({"a.mkv", "b.mkv"}, {}, {"a.mkv": "A.mkv"}, {"b.mkv"}, set())

    assert outcome.missing == ["a.mkv"]


def test_files_left_in_the_old_folder_are_reported_once():
    outcome = check_files(
        {"a.mkv", "b.mkv"}, {}, {"b.mkv": "B.mkv"}, set(), {"a.mkv", "B.mkv"}
    )

    assert outcome.left_behind == ["B.mkv", "a.mkv"]
    assert outcome.missing == []


def test_a_new_download_is_not_a_problem():
    outcome = check_files({"a.mkv"}, {1: "a.mkv"}, {}, {"a.mkv", "new.mkv"}, set())

    assert outcome.missing == []


def test_records_drift_when_one_still_points_at_the_old_name():
    assert records_drifted({1: "A.mkv"}, {1: "a.mkv"}) is True
    assert records_drifted({1: "A.mkv"}, {1: "A.mkv", 9: "new.mkv"}) is False


def test_untracked_lists_files_on_disk_with_no_record():
    assert untracked({1: "A.mkv", 2: "gone.mkv"}, {}, {"A.mkv"}) == ["A.mkv"]


@pytest.mark.parametrize(
    "current, expected, reasons",
    [
        ("Blade Runner 2049 (2017)", "Blade Runner 2049 (2017) {imdb-tt1856101}", []),
        ("Show [tvdbid-123]", "Show {tvdb-123}", []),
        ("Show {imdb-tt1}", "Show {imdb-}", ["the new name has an empty imdb id"]),
        ("1917 (2019)", "1917", ["the new name drops the year 2019"]),
        ("Show (2011-2015)", "Show", []),
        ("Show (2011)", "(2011)", ["the new name has no title"]),
    ],
)
def test_irregular_reasons_shapes(current, expected, reasons):
    got = irregular_reasons(current, expected)
    assert got == reasons


def test_case_only_move_with_a_case_twin_on_disk_is_blocked():
    item = {"path": "/tv/show", "root_folder": "/tv", "media_id": 1}
    verdict = plan_folder(item, "Show", {"/tv/show"}, {"show", "Show"})
    assert verdict.action == BLOCKED


def test_windows_hosted_arr_block_reason_is_not_a_false_subfolder_claim():
    item = {"path": "D:\\TV\\Show", "root_folder": "D:\\TV", "media_id": 1}
    verdict = plan_folder(item, "Show (2011)", set(), {"Show"})
    assert verdict.action == BLOCKED
    assert verdict.reason == "folder renames don't support Windows paths"

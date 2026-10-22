"""Renameinatorr's Discord report: renames and problems listed, held and blocked folders counted."""

from types import SimpleNamespace

from backend.util.notification_formatting import format_for_discord


def _item(title, **fields):
    item = {
        "title": title,
        "year": 2011,
        "path_name": title,
        "new_path_name": None,
        "file_info": {},
        "held": None,
        "blocked": None,
        "problems": [],
    }
    item.update(fields)
    return item


def _fields(data, stopped=None):
    output = {"sonarr": {"server_name": "Sonarr", "data": data, "stopped": stopped}}
    embeds, ok = format_for_discord(
        SimpleNamespace(module_name="renameinatorr"), output
    )
    assert ok is True
    return [field for embed in embeds.values() for field in embed]


def _named(fields, name):
    return [f["value"] for f in fields if f["name"] == name]


def test_held_and_blocked_folders_are_counted_not_listed():
    fields = _fields(
        [
            _item("Held Show", held="the new name drops the year 2011"),
            _item("Blocked Show", blocked="a folder with that name already exists"),
        ]
    )

    (summary,) = _named(fields, "Summary")
    assert "1 folder rename(s) held" in summary
    assert "1 folder(s) not renamed" in summary
    assert "Held Show" not in summary and "Blocked Show" not in summary
    assert _named(fields, "Renamed") == []


def test_problems_and_a_stop_are_reported():
    fields = _fields(
        [
            _item(
                "Broken Show",
                problems=["1 file(s) went missing, so it wasn't refreshed"],
            )
        ],
        stopped="some renamed items' files need checking (see their problems)",
    )

    (summary,) = _named(fields, "Summary")
    (problems,) = _named(fields, "Problems")
    assert "Stopped on Sonarr" in summary
    assert "Broken Show (2011)" in problems
    assert "went missing" in problems


def test_renames_are_still_listed():
    fields = _fields(
        [_item("Show", new_path_name="Show (2011)", file_info={"a.mkv": "A.mkv"})]
    )

    (renamed,) = _named(fields, "Renamed")
    assert "Show -> Show (2011)" in renamed
    assert "A.mkv" in renamed
    assert _named(fields, "Summary") == []


def test_a_quiet_run_sends_nothing():
    fields = _fields([_item("Show")])

    assert fields == []

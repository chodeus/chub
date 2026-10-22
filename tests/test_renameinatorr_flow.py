"""Renameinatorr against a fake *arr: what it renames, what it holds back, and when it refreshes."""

import posixpath
import threading
from types import SimpleNamespace

from backend.modules.renameinatorr import Renameinatorr

ROOT = "/data/media/tv"


class _Silent:
    def _noop(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = _noop


def _shared_session_check(threadsafe):
    # The client's shared session isn't thread-safe, so a worker thread must ask for its own
    if threading.current_thread() is not threading.main_thread() and not threadsafe:
        raise AssertionError("a worker thread read through the shared session")


def _show(folder, expected=None, files=("a.mkv",), renames=None):
    return folder, expected or folder, files, dict(renames or {})


class _FakeArr:
    """Items with folders and files on a fake disk; renames and moves apply when their wait runs."""

    instance_name = "sonarr_main"
    RENAME_COMMAND = "RenameSeries"
    FOLDER_MOVE_COMMAND = "BulkMoveSeries"

    def __init__(
        self,
        shows,
        *,
        extra_folders=(),
        idle=(),
        renames_finish=True,
        moves_finish=True,
        renames_apply=True,
        lose_on_move=(),
        stale_records=(),
        absolute_previews=False,
        unreadable=(),
        case_insensitive=False,
    ):
        self.calls = []
        self.paths, self.expected, self.previews = {}, {}, {}
        self.disk, self.records = {}, {}
        for media_id, (folder, expected, files, renames) in shows.items():
            path = f"{ROOT}/{folder}"
            self.paths[media_id] = path
            self.expected[media_id] = expected
            self.previews[media_id] = renames
            self.disk[path] = set(files)
            self.records[media_id] = dict(enumerate(sorted(files)))
        self.extra_folders = set(extra_folders)
        self._idle = list(idle)
        self.renames_finish = renames_finish
        self.moves_finish = moves_finish
        self.renames_apply = renames_apply
        self.lose_on_move = set(lose_on_move)
        self.stale_records = set(stale_records)
        self.absolute_previews = absolute_previews
        self.unreadable = set(unreadable)
        self.case_insensitive = case_insensitive
        self.move_request_fails = False
        self._renaming, self._moving = [], []

    def get_all_media(self):
        return [
            {
                "media_id": media_id,
                "tags": [],
                "title": f"Show {media_id}",
                "year": 2011,
                "path": path,
                "path_name": posixpath.basename(path),
                "root_folder": ROOT,
            }
            for media_id, path in self.paths.items()
        ]

    def get_all_tags(self):
        return []

    def command_ids(self, name):
        return {7}

    def get_rename_list(self, media_id, threadsafe=False):
        _shared_session_check(threadsafe)
        prefix = self.paths[media_id] + "/" if self.absolute_previews else ""
        return [
            {"existingPath": prefix + old, "newPath": prefix + new}
            for old, new in self.previews[media_id].items()
        ]

    def get_expected_folder(self, item, threadsafe=False):
        _shared_session_check(threadsafe)
        return self.expected[item["media_id"]]

    def list_folders(self, path):
        on_disk = {
            posixpath.basename(p) for p in self.disk if posixpath.dirname(p) == path
        }
        return on_disk | self.extra_folders

    def get_media_files(self, folder, threadsafe=False):
        _shared_session_check(threadsafe)
        self.calls.append("read files")
        if folder in self.unreadable:
            return None
        if self.case_insensitive:
            folder = next((p for p in self.disk if p.lower() == folder.lower()), folder)
        return set(self.disk.get(folder, set()))

    def get_file_records(self, media_id, folder, threadsafe=False):
        _shared_session_check(threadsafe)
        return dict(self.records[media_id])

    def wait_for_refreshes(self, label=""):
        self.calls.append("wait for refreshes")
        return self._idle.pop(0) if self._idle else True

    def rename_media(self, ids):
        self.calls.append(("rename", sorted(ids)))
        self._renaming = list(ids)
        return {"id": 2}

    def rename_folders(self, ids, root_folder):
        self.calls.append(("move", sorted(ids)))
        if self.move_request_fails:
            return None
        self._moving += list(ids)
        return []

    def wait_for_commands_to_finish(self, names, label="", ignore_ids=None):
        (name,) = names
        self.calls.append(f"wait for {name}")
        if name == self.RENAME_COMMAND:
            if self.renames_apply:
                self._apply_renames()
            return self.renames_finish
        self._apply_moves()
        return self.moves_finish

    def _apply_renames(self):
        for media_id in self._renaming:
            files = self.disk[self.paths[media_id]]
            for old, new in self.previews[media_id].items():
                files.discard(old)
                files.add(new)
                if media_id not in self.stale_records:
                    self.records[media_id] = {
                        k: new if v == old else v
                        for k, v in self.records[media_id].items()
                    }
            self.previews[media_id] = {}

    def _apply_moves(self):
        for media_id in self._moving:
            old = self.paths[media_id]
            new = f"{ROOT}/{self.expected[media_id]}"
            self.disk[new] = self.disk.pop(old) - self.lose_on_move
            self.paths[media_id] = new
        self._moving = []

    def refresh_and_wait(self, ids):
        self.calls.append(("refresh", sorted(ids)))
        for media_id in ids:
            self.records[media_id] = dict(
                enumerate(sorted(self.disk[self.paths[media_id]]))
            )
        return True

    def add_tags(self, ids, tag_id):
        self.calls.append(("tag", sorted(ids)))

    def get_tag_id_from_name(self, name):
        return 9


def _run(app, **overrides):
    cfg = dict(
        count=0,
        radarr_count=0,
        sonarr_count=0,
        tag_name="",
        ignore_tags="",
        enable_batching=False,
        dry_run=False,
        rename_folders=True,
        refresh_before_rename=False,
    )
    cfg.update(overrides)
    m = object.__new__(Renameinatorr)
    m._cancel_event = None
    data, stopped = m.process_instance(app, "sonarr", SimpleNamespace(**cfg), _Silent())
    return {item["title"]: item for item in data}, stopped


def _sent(app, kind):
    return [
        call[1] for call in app.calls if isinstance(call, tuple) and call[0] == kind
    ]


def test_moves_only_the_folders_that_need_it():
    app = _FakeArr(
        {1: _show("Show One", "Show One (2011)"), 2: _show("Show Two (2011)")}
    )

    report, stopped = _run(app)

    assert _sent(app, "move") == [[1]]
    assert _sent(app, "rename") == []
    assert report["Show 1"]["new_path_name"] == "Show One (2011)"
    assert report["Show 2"]["new_path_name"] is None
    assert stopped is None


def test_a_dry_run_shows_the_folder_renames_without_making_them():
    app = _FakeArr(
        {1: _show("Show One", "Show One (2011)", renames={"a.mkv": "A.mkv"})}
    )

    report, _ = _run(app, dry_run=True)

    assert report["Show 1"]["new_path_name"] == "Show One (2011)"
    assert report["Show 1"]["file_info"] == {"a.mkv": "A.mkv"}
    assert app.calls == []
    assert app.paths[1] == f"{ROOT}/Show One"


def test_a_rename_that_drops_the_year_is_held():
    app = _FakeArr({1: _show("Show (2011)", "Show")})

    report, stopped = _run(app)

    assert _sent(app, "move") == []
    assert "drops the year 2011" in report["Show 1"]["held"]
    assert stopped is None


def test_a_folder_that_would_merge_into_another_is_blocked():
    app = _FakeArr({1: _show("Show", "Show (2011)")}, extra_folders={"Show (2011)"})

    report, _ = _run(app)

    assert _sent(app, "move") == []
    assert "already exists" in report["Show 1"]["blocked"]


def test_renames_only_the_items_whose_preview_lists_files():
    app = _FakeArr({1: _show("One", renames={"a.mkv": "A.mkv"}), 2: _show("Two")})

    report, _ = _run(app, rename_folders=False)

    assert _sent(app, "rename") == [[1]]
    assert report["Show 1"]["file_info"] == {"a.mkv": "A.mkv"}


def test_does_nothing_when_nothing_needs_renaming():
    app = _FakeArr({1: _show("One"), 2: _show("Two")})

    _, stopped = _run(app)

    assert app.calls == []
    assert stopped is None


def test_waits_for_running_refreshes_before_renaming_and_before_moving():
    app = _FakeArr({1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})})

    _run(app)

    assert [c for c in app.calls if c != "read files"][:6] == [
        "wait for refreshes",
        ("rename", [1]),
        "wait for RenameSeries",
        "wait for refreshes",
        ("move", [1]),
        "wait for BulkMoveSeries",
    ]


def test_the_rename_is_sent_straight_after_the_refresh_wait():
    app = _FakeArr(
        {n: _show(f"Show {n}", renames={"a.mkv": "A.mkv"}) for n in range(1, 4)}
    )

    _run(app, rename_folders=False)

    wait = app.calls.index("wait for refreshes")
    assert app.calls[wait + 1] == ("rename", [1, 2, 3])
    assert "read files" in app.calls[:wait]


def test_a_refresh_still_running_stops_the_batch_before_any_change():
    app = _FakeArr(
        {1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})}, idle=[False]
    )

    report, stopped = _run(app)

    assert _sent(app, "rename") == [] and _sent(app, "move") == []
    assert report["Show 1"]["file_info"] == {}
    assert "refresh was still running" in stopped


def test_a_refresh_still_running_before_the_move_leaves_the_folders_alone():
    app = _FakeArr(
        {1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})}, idle=[True, False]
    )

    report, stopped = _run(app)

    assert _sent(app, "move") == []
    assert report["Show 1"]["file_info"] == {"a.mkv": "A.mkv"}
    assert report["Show 1"]["new_path_name"] is None
    assert "folders weren't renamed" in stopped


def test_renames_that_do_not_finish_stop_before_the_moves():
    app = _FakeArr(
        {1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})},
        renames_finish=False,
    )

    report, stopped = _run(app)

    assert _sent(app, "move") == [] and _sent(app, "refresh") == []
    assert report["Show 1"]["file_info"] == {}
    assert "file renames didn't finish" in stopped


def test_moves_that_do_not_finish_are_not_checked_or_refreshed():
    app = _FakeArr(
        {1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})},
        moves_finish=False,
        stale_records={1},
    )

    report, stopped = _run(app)

    assert _sent(app, "refresh") == []
    assert report["Show 1"]["file_info"] == {}
    assert "folder moves didn't finish" in stopped


def test_does_not_refresh_when_the_records_match():
    app = _FakeArr({1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})})

    report, stopped = _run(app)

    assert _sent(app, "refresh") == []
    assert report["Show 1"]["file_info"] == {"a.mkv": "A.mkv"}
    assert report["Show 1"]["new_path_name"] == "One (2011)"
    assert stopped is None


def test_refreshes_only_the_items_whose_records_drifted():
    app = _FakeArr(
        {
            1: _show("One", renames={"a.mkv": "A.mkv"}),
            2: _show("Two", renames={"a.mkv": "A.mkv"}),
        },
        stale_records={2},
    )

    report, stopped = _run(app)

    assert _sent(app, "refresh") == [[2]]
    assert report["Show 2"]["problems"] == []
    assert stopped is None


def test_a_file_lost_in_the_move_is_reported_and_not_refreshed():
    app = _FakeArr(
        {
            1: _show(
                "One",
                "One (2011)",
                files=("a.mkv", "b.mkv"),
                renames={"a.mkv": "A.mkv"},
            )
        },
        lose_on_move={"b.mkv"},
        stale_records={1},
    )

    report, stopped = _run(app)

    assert _sent(app, "refresh") == []
    assert any("went missing" in p for p in report["Show 1"]["problems"])
    assert stopped is not None


def test_a_problem_stops_the_later_batches():
    app = _FakeArr(
        {
            1: _show("One", "One (2011)", files=("a.mkv", "b.mkv")),
            2: _show("Two", "Two (2011)"),
        },
        lose_on_move={"b.mkv"},
    )

    report, stopped = _run(app, enable_batching=True, count=1)

    assert _sent(app, "move") == [[1]]
    assert "Show 2" not in report
    assert stopped is not None


def test_a_rename_the_arr_did_not_make_is_not_reported():
    app = _FakeArr({1: _show("One", renames={"a.mkv": "A.mkv"})}, renames_apply=False)

    report, stopped = _run(app)

    assert report["Show 1"]["file_info"] == {}
    assert any("weren't renamed" in p for p in report["Show 1"]["problems"])
    assert stopped is None


def test_lidarr_style_absolute_preview_paths_are_checked_relative_to_the_folder():
    app = _FakeArr(
        {
            1: _show(
                "Artist",
                files=("Album/01.flac",),
                renames={"Album/01.flac": "Album/01 - Song.flac"},
            )
        },
        absolute_previews=True,
    )

    report, stopped = _run(app, rename_folders=False)

    assert report["Show 1"]["file_info"] == {"Album/01.flac": "Album/01 - Song.flac"}
    assert _sent(app, "refresh") == []
    assert stopped is None


def test_an_item_whose_files_cannot_be_read_is_left_alone():
    app = _FakeArr(
        {
            1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"}),
            2: _show("Two", renames={"a.mkv": "A.mkv"}),
        },
        unreadable={f"{ROOT}/One"},
    )

    report, stopped = _run(app)

    assert _sent(app, "rename") == [[2]]
    assert _sent(app, "move") == []
    assert report["Show 1"]["file_info"] == {}
    assert "couldn't be read, so it was left alone" in report["Show 1"]["problems"][0]
    assert stopped is None


def test_an_item_with_a_problem_is_still_tagged_so_the_cycle_moves_on():
    app = _FakeArr(
        {1: _show("One", renames={"a.mkv": "A.mkv"}), 2: _show("Two")},
        renames_apply=False,
    )

    report, _ = _run(app, tag_name="renamed")

    assert report["Show 1"]["problems"]
    assert _sent(app, "tag") == [[1, 2]]


def test_a_skipped_move_leaves_the_batch_untagged_for_the_next_run():
    app = _FakeArr(
        {1: _show("One", renames={"a.mkv": "A.mkv"}), 2: _show("Two", "Two (2011)")},
        idle=[True, False],
    )

    _, stopped = _run(app, tag_name="renamed")

    assert "folders weren't renamed" in stopped
    assert _sent(app, "tag") == []


def test_unreadable_folder_names_stop_the_batch_before_any_change():
    app = _FakeArr({1: _show("One", renames={"a.mkv": "A.mkv"})})
    app.expected[1] = None

    _, stopped = _run(app, tag_name="renamed")

    assert "folder names couldn't be read" in stopped
    assert app.calls == []


def test_one_unreadable_folder_name_blocks_only_that_item():
    app = _FakeArr({1: _show("One", "One (2011)"), 2: _show("Two", "Two (2011)")})
    app.expected[1] = None

    report, stopped = _run(app)

    assert "couldn't be read" in report["Show 1"]["blocked"]
    assert _sent(app, "move") == [[2]]
    assert stopped is None


def test_an_unlistable_root_folder_stops_the_batch_before_any_change():
    app = _FakeArr({1: _show("One", "One (2011)", renames={"a.mkv": "A.mkv"})})
    app.list_folders = lambda path: None

    _, stopped = _run(app, tag_name="renamed")

    assert "root folder couldn't be listed" in stopped
    assert app.calls == []


def test_a_case_only_rename_on_a_case_insensitive_disk_leaves_nothing_behind():
    app = _FakeArr({1: _show("show (2011)", "Show (2011)")}, case_insensitive=True)

    report, stopped = _run(app)

    assert report["Show 1"]["new_path_name"] == "Show (2011)"
    assert report["Show 1"]["problems"] == []
    assert stopped is None


def test_an_unlistable_root_folder_does_not_matter_when_no_folder_moves():
    app = _FakeArr({1: _show("One", renames={"a.mkv": "A.mkv"})})
    app.list_folders = lambda path: None

    report, stopped = _run(app)

    assert report["Show 1"]["file_info"] == {"a.mkv": "A.mkv"}
    assert stopped is None


def test_an_item_the_arr_has_no_folder_name_for_is_blocked_and_tagged():
    app = _FakeArr({1: _show("One", renames={"a.mkv": "A.mkv"}), 2: _show("Two")})
    app.expected[1] = ""

    report, stopped = _run(app, tag_name="renamed")

    assert report["Show 1"]["blocked"] == "the arr has no folder name for it"
    assert report["Show 1"]["file_info"] == {"a.mkv": "A.mkv"}
    assert _sent(app, "tag") == [[1, 2]]
    assert stopped is None


def test_an_item_whose_folder_name_failed_to_read_is_left_untagged():
    app = _FakeArr({1: _show("One", "One (2011)"), 2: _show("Two", "Two (2011)")})
    app.expected[1] = None

    _, stopped = _run(app, tag_name="renamed")

    assert _sent(app, "tag") == [[2]]
    assert stopped is None


def test_a_failed_move_request_stops_the_batch_untagged():
    app = _FakeArr({1: _show("One", "One (2011)")})
    app.move_request_fails = True

    report, stopped = _run(app, tag_name="renamed")

    assert report["Show 1"]["problems"] == [
        "its folder wasn't renamed: the move request failed"
    ]
    assert "request to the arr failed" in stopped
    assert _sent(app, "tag") == []


def test_files_unreadable_after_the_change_leave_the_item_untagged():
    app = _FakeArr({1: _show("One", renames={"a.mkv": "A.mkv"}), 2: _show("Two")})
    reads = []
    real = app.get_file_records

    def records(media_id, folder, threadsafe=False):
        reads.append(media_id)
        if media_id == 1 and reads.count(1) > 1:
            return None
        return real(media_id, folder, threadsafe)

    app.get_file_records = records

    report, stopped = _run(app, tag_name="renamed")

    assert report["Show 1"]["problems"] == [
        "its files couldn't be read after the change"
    ]
    assert stopped is not None
    assert _sent(app, "tag") == [[2]]

"""Renameinatorr's folder rename refreshes only once the *arr's bulk move has finished."""

from types import SimpleNamespace

import pytest

from backend.modules.renameinatorr import Renameinatorr
from backend.util import arr as arr_mod
from backend.util.arr import (
    COMMAND_MAX_POLL_ERRORS,
    COMMAND_POLL_SECONDS,
    COMMAND_RUN_TIMEOUT_SECONDS,
    BaseARRClient,
    LidarrClient,
    RadarrClient,
    SonarrClient,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now


class _Silent:
    def _noop(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = _noop


def _client(responses, monkeypatch, cls=BaseARRClient):
    clock = _Clock()
    monkeypatch.setattr(arr_mod, "time", clock)

    client = cls.__new__(cls)
    client.url = "http://arr.test"
    client.api_version = "v3"
    client.logger = _Silent()
    client.instance_name = "sonarr_main"

    seq = list(responses)

    def fake_get(_endpoint):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    client.make_get_request = fake_get
    return client, clock


def _move(status, command_id=1):
    return [{"id": command_id, "name": "BulkMoveSeries", "status": status}]


def test_waits_until_the_move_has_finished(monkeypatch):
    client, clock = _client(
        [_move("queued"), _move("started"), _move("completed")], monkeypatch
    )

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is True
    assert clock.now == 2 * COMMAND_POLL_SECONDS


def test_a_failed_move_is_not_a_finished_one(monkeypatch):
    client, _ = _client([_move("started"), _move("failed")], monkeypatch)

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is False


def test_a_move_that_failed_in_an_earlier_run_is_ignored(monkeypatch):
    client, _ = _client([_move("failed", 1) + _move("completed", 2)], monkeypatch)

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"], ignore_ids={1})

    assert finished is True


def test_any_failed_move_from_this_run_fails_the_wait(monkeypatch):
    client, _ = _client([_move("failed", 1) + _move("completed", 2)], monkeypatch)

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is False


def test_a_failure_dropped_from_the_list_still_fails_the_wait(monkeypatch):
    client, _ = _client(
        [_move("failed", 1) + _move("started", 2), _move("completed", 2)], monkeypatch
    )

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is False


def test_lists_the_move_commands_already_known(monkeypatch):
    client, _ = _client(
        [_move("completed", 3) + [{"id": 4, "name": "RefreshSeries", "status": "started"}]],
        monkeypatch,
        SonarrClient,
    )

    known = client.command_ids(client.FOLDER_MOVE_COMMAND)

    assert known == {3}


def test_other_commands_do_not_hold_it_up(monkeypatch):
    client, clock = _client(
        [[{"name": "RefreshSeries", "status": "started"}]], monkeypatch
    )

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is True
    assert clock.now == 0


def test_gives_up_when_the_command_list_cannot_be_read(monkeypatch):
    client, clock = _client(["<html>proxy error</html>"], monkeypatch)

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is False
    assert clock.now == (COMMAND_MAX_POLL_ERRORS - 1) * COMMAND_POLL_SECONDS


def test_gives_up_after_the_run_timeout(monkeypatch):
    client, clock = _client([_move("started")], monkeypatch)

    finished = client.wait_for_commands_to_finish(["BulkMoveSeries"])

    assert finished is False
    assert COMMAND_RUN_TIMEOUT_SECONDS <= clock.now < COMMAND_RUN_TIMEOUT_SECONDS + COMMAND_POLL_SECONDS


@pytest.mark.parametrize(
    "cls, command",
    [
        (SonarrClient, "BulkMoveSeries"),
        (RadarrClient, "BulkMoveMovie"),
        (LidarrClient, "BulkMoveArtist"),
    ],
)
def test_each_client_names_its_own_bulk_move(cls, command):
    assert cls.FOLDER_MOVE_COMMAND == command


@pytest.mark.parametrize("cls", [SonarrClient, RadarrClient, LidarrClient])
def test_each_client_waits_for_the_rename_command_it_posts(monkeypatch, cls):
    client, _ = _client([[]], monkeypatch, cls)
    posted = []
    client.get_rename_list = lambda media_id, threadsafe=False: [{"trackFileId": 1}]
    client.make_post_request = lambda endpoint, json=None: posted.append(json) or {"id": 2}

    client.rename_media([13])

    assert [p["name"] for p in posted] == [cls.RENAME_COMMAND]


class _RenameApp:
    instance_name = "sonarr_main"
    RENAME_COMMAND = "RenameSeries"
    FOLDER_MOVE_COMMAND = "BulkMoveSeries"

    def __init__(
        self,
        moves_finish=True,
        failed_roots=(),
        roots=("/data/media/tv",),
        files_to_rename=False,
        renames_finish=True,
    ):
        self.calls = []
        self.ignored = {}
        self._finishes = {self.FOLDER_MOVE_COMMAND: moves_finish, self.RENAME_COMMAND: renames_finish}
        self._failed_roots = set(failed_roots)
        self._roots = roots
        self._files_to_rename = files_to_rename

    def get_all_media(self):
        self.calls.append("get_all_media")
        return [
            {
                "media_id": 13 + i,
                "tags": [],
                "title": f"Series {i}",
                "year": 2011,
                "path_name": f"Series {i} (2011)",
                "root_folder": root,
            }
            for i, root in enumerate(self._roots)
        ]

    def command_ids(self, name):
        return {7} if name == self.FOLDER_MOVE_COMMAND else {8}

    def get_all_tags(self):
        return []

    def get_rename_list(self, media_id, threadsafe=False):
        if not self._files_to_rename:
            return []
        return [{"existingPath": "Series 0 - S01E01.mkv", "newPath": "Series 0 - S01E01 - Pilot.mkv"}]

    def rename_media(self, ids):
        self.calls.append("rename_media")

    def rename_folders(self, ids, root_folder):
        self.calls.append("rename_folders")
        return None if root_folder in self._failed_roots else []

    def wait_for_commands_to_finish(self, names, label="", ignore_ids=None):
        (name,) = names
        self.calls.append(f"wait:{name}")
        self.ignored[name] = ignore_ids
        return self._finishes[name]

    def refresh_items(self, ids):
        self.calls.append("refresh_items")
        return {"id": 1}

    def wait_for_command(self, command_id):
        self.calls.append("wait_for_command")
        return True


def _cfg(rename_folders=True):
    return SimpleNamespace(
        count=0,
        radarr_count=0,
        sonarr_count=0,
        tag_name="",
        ignore_tags="",
        enable_batching=False,
        dry_run=False,
        rename_folders=rename_folders,
        refresh_before_rename=False,
    )


class _Recorder(_Silent):
    def __init__(self):
        self.infos = []

    def info(self, message, *_a, **_k):
        self.infos.append(message)


def _run(app, logger=None, rename_folders=True):
    m = object.__new__(Renameinatorr)
    m._cancel_event = None
    m.process_instance(app, "sonarr", _cfg(rename_folders), logger or _Silent())


def test_refreshes_only_after_the_folder_moves_finish():
    app = _RenameApp()

    _run(app)

    after_move = app.calls[app.calls.index("rename_folders") :]
    assert after_move[:3] == ["rename_folders", "wait:BulkMoveSeries", "refresh_items"]
    assert app.ignored["BulkMoveSeries"] == {7}


@pytest.mark.parametrize(
    "roots, failed_roots",
    [
        (("/data/media/tv",), ("/data/media/tv",)),
        (("/data/media/tv", "/data/media/anime"), ("/data/media/tv",)),
    ],
)
def test_skips_the_refresh_when_a_folder_move_request_fails(roots, failed_roots):
    app = _RenameApp(roots=roots, failed_roots=failed_roots)
    logger = _Recorder()

    _run(app, logger)

    assert "refresh_items" not in app.calls
    assert not [m for m in logger.infos if m.startswith("Folder moves finished")]


def test_skips_the_refresh_when_the_folder_moves_do_not_finish():
    app = _RenameApp(moves_finish=False)
    logger = _Recorder()

    _run(app, logger)

    after_move = app.calls[app.calls.index("rename_folders") :]
    assert after_move == ["rename_folders", "wait:BulkMoveSeries"]
    assert not [m for m in logger.infos if m.startswith("Folder moves finished")]


def test_reports_the_folder_moves_finished_once_they_do():
    logger = _Recorder()

    _run(_RenameApp(), logger)

    assert [m for m in logger.infos if m.startswith("Folder moves finished")]


def test_refreshes_only_after_the_renames_finish():
    app = _RenameApp(files_to_rename=True)

    _run(app, rename_folders=False)

    after_rename = app.calls[app.calls.index("rename_media") :]
    assert after_rename[:3] == ["rename_media", "wait:RenameSeries", "refresh_items"]
    assert app.ignored["RenameSeries"] == {8}


def test_skips_the_refresh_when_the_renames_do_not_finish():
    app = _RenameApp(files_to_rename=True, renames_finish=False)

    _run(app, rename_folders=False)

    after_rename = app.calls[app.calls.index("rename_media") :]
    assert after_rename == ["rename_media", "wait:RenameSeries"]


def test_waits_but_does_not_refresh_when_the_preview_showed_no_renames():
    app = _RenameApp(files_to_rename=False)

    _run(app, rename_folders=False)

    after_rename = app.calls[app.calls.index("rename_media") :]
    assert after_rename == ["rename_media", "wait:RenameSeries"]


def test_skips_the_folder_refresh_when_unpreviewed_renames_do_not_finish():
    app = _RenameApp(files_to_rename=False, renames_finish=False)

    _run(app, rename_folders=True)

    assert "rename_folders" in app.calls
    assert "refresh_items" not in app.calls


def test_skips_the_folder_refresh_when_the_renames_do_not_finish():
    app = _RenameApp(files_to_rename=True, renames_finish=False)

    _run(app, rename_folders=True)

    assert "rename_folders" in app.calls
    assert "refresh_items" not in app.calls


def test_refreshes_after_both_stages_when_both_finish():
    app = _RenameApp(files_to_rename=True)

    _run(app, rename_folders=True)

    after_move = app.calls[app.calls.index("rename_folders") :]
    assert after_move[:3] == ["rename_folders", "wait:BulkMoveSeries", "refresh_items"]


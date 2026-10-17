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


def test_lists_the_move_commands_already_known(monkeypatch):
    client, _ = _client(
        [_move("completed", 3) + [{"id": 4, "name": "RefreshSeries", "status": "started"}]],
        monkeypatch,
        SonarrClient,
    )

    known = client.folder_move_command_ids()

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
def test_each_client_waits_for_its_own_bulk_move(monkeypatch, cls, command):
    client, _ = _client([[]], monkeypatch, cls)
    waited = []
    client.wait_for_commands_to_finish = lambda names, label="", ignore_ids=None: waited.append(
        (list(names), ignore_ids)
    ) or True

    finished = client.wait_for_folder_moves({5})

    assert finished is True
    assert waited == [([command], {5})]


class _FolderRenameApp:
    instance_name = "sonarr_main"

    def __init__(self, moves_finish=True, failed_roots=(), roots=("/data/media/tv",)):
        self.calls = []
        self.waited_ignoring = None
        self._moves_finish = moves_finish
        self._failed_roots = set(failed_roots)
        self._roots = roots

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

    def folder_move_command_ids(self):
        return {7}

    def get_all_tags(self):
        return []

    def get_rename_list(self, media_id, threadsafe=False):
        return []

    def rename_media(self, ids):
        self.calls.append("rename_media")

    def rename_folders(self, ids, root_folder):
        self.calls.append("rename_folders")
        return None if root_folder in self._failed_roots else []

    def wait_for_folder_moves(self, earlier_ids):
        self.calls.append("wait_for_folder_moves")
        self.waited_ignoring = earlier_ids
        return self._moves_finish

    def refresh_items(self, ids):
        self.calls.append("refresh_items")
        return {"id": 1}

    def wait_for_command(self, command_id):
        self.calls.append("wait_for_command")
        return True


def _folder_cfg():
    return SimpleNamespace(
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


class _Recorder(_Silent):
    def __init__(self):
        self.infos = []

    def info(self, message, *_a, **_k):
        self.infos.append(message)


def _run(app, logger=None):
    m = object.__new__(Renameinatorr)
    m._cancel_event = None
    m.process_instance(app, "sonarr", _folder_cfg(), logger or _Silent())


def test_refreshes_only_after_the_folder_moves_finish():
    app = _FolderRenameApp()

    _run(app)

    after_move = app.calls[app.calls.index("rename_folders") :]
    assert after_move[:3] == ["rename_folders", "wait_for_folder_moves", "refresh_items"]
    assert app.waited_ignoring == {7}


@pytest.mark.parametrize(
    "roots, failed_roots",
    [
        (("/data/media/tv",), ("/data/media/tv",)),
        (("/data/media/tv", "/data/media/anime"), ("/data/media/tv",)),
    ],
)
def test_skips_the_refresh_when_a_folder_move_request_fails(roots, failed_roots):
    app = _FolderRenameApp(roots=roots, failed_roots=failed_roots)
    logger = _Recorder()

    _run(app, logger)

    assert "refresh_items" not in app.calls
    assert not [m for m in logger.infos if m.startswith("Folders renamed")]


def test_skips_the_refresh_when_the_folder_moves_do_not_finish():
    app = _FolderRenameApp(moves_finish=False)
    logger = _Recorder()

    _run(app, logger)

    after_move = app.calls[app.calls.index("rename_folders") :]
    assert after_move == ["rename_folders", "wait_for_folder_moves"]
    assert not [m for m in logger.infos if m.startswith("Folders renamed")]


def test_reports_folders_renamed_once_the_moves_finish():
    logger = _Recorder()

    _run(_FolderRenameApp(), logger)

    assert [m for m in logger.infos if m.startswith("Folders renamed")]

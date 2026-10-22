"""The *arr command waits renameinatorr relies on before it renames, moves or checks."""

import pytest

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


def test_waiting_for_idle_ignores_how_other_commands_ended(monkeypatch):
    client, _ = _client([_move("failed", 1)], monkeypatch)

    finished = client.wait_for_commands_to_finish(
        ["BulkMoveSeries"], require_success=False
    )

    assert finished is True


@pytest.mark.parametrize(
    "cls, command",
    [
        (SonarrClient, "RefreshSeries"),
        (SonarrClient, "RescanSeries"),
        (RadarrClient, "RefreshMovie"),
        (RadarrClient, "RescanMovie"),
        (LidarrClient, "RefreshArtist"),
    ],
)
def test_waits_for_a_running_refresh_or_rescan(monkeypatch, cls, command):
    running = [{"id": 1, "name": command, "status": "started"}]
    done = [{"id": 1, "name": command, "status": "failed"}]
    client, clock = _client([running, done], monkeypatch, cls)

    idle = client.wait_for_refreshes()

    assert idle is True
    assert clock.now == COMMAND_POLL_SECONDS


def test_gives_up_on_a_refresh_still_running_after_the_run_timeout(monkeypatch):
    client, _ = _client(
        [[{"id": 1, "name": "RefreshSeries", "status": "started"}]],
        monkeypatch,
        SonarrClient,
    )

    idle = client.wait_for_refreshes()

    assert idle is False


def _lidarr(monkeypatch, scans):
    client, clock = _client([[]], monkeypatch, LidarrClient)
    lists = list(scans)

    def fake_get(endpoint, headers=None, params=None):
        if endpoint.endswith("/command/5"):
            return {"id": 5, "name": "RefreshArtist", "status": "completed"}
        return lists.pop(0) if len(lists) > 1 else lists[0]

    client.make_get_request = fake_get
    client.make_post_request = lambda endpoint, json=None, headers=None: {"id": 5}
    return client, clock


def _scan(status, command_id=6):
    return {"id": command_id, "name": "RescanFolders", "status": status}


def test_lidarr_refresh_waits_for_the_rescan_it_queues(monkeypatch):
    old = _scan("failed", 3)
    client, clock = _lidarr(
        monkeypatch, [[old], [old, _scan("started")], [old, _scan("completed")]]
    )

    refreshed = client.refresh_and_wait([1])

    assert refreshed is True
    assert clock.now == COMMAND_POLL_SECONDS


def test_lidarr_refresh_fails_when_its_rescan_fails(monkeypatch):
    client, _ = _lidarr(monkeypatch, [[], [_scan("started")], [_scan("failed")]])

    refreshed = client.refresh_and_wait([1])

    assert refreshed is False


def test_a_refresh_with_no_command_id_is_not_complete(monkeypatch):
    client, _ = _client([[]], monkeypatch, SonarrClient)
    client.headers = {}
    client.make_post_request = lambda endpoint, json=None, headers=None: "<html>"

    refreshed = client.refresh_and_wait([1])

    assert refreshed is False

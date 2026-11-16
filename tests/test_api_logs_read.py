"""The Logs page reads a module log once (its last VIEW_CAP bytes when bigger), then only the whole lines added since."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.logs as logs

URL = "/api/logs/poster_renamerr/poster_renamerr.log"


class _StubLogger:
    def debug(self, *a, **kw):
        """No-op."""

    def error(self, *a, **kw):
        """No-op."""

    def get_adapter(self, _source):
        return self


@pytest.fixture
def log(tmp_path, monkeypatch):
    """(client, path of a real poster_renamerr.log under LOG_DIR)."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    (tmp_path / "poster_renamerr").mkdir()
    app = FastAPI()
    app.state.logger = _StubLogger()
    app.include_router(logs.router)
    return TestClient(app), tmp_path / "poster_renamerr" / "poster_renamerr.log"


def _view(client, offset=0, log_id="", start=0):
    resp = client.get(URL, params={"offset": offset, "id": log_id, "start": start})
    assert resp.status_code == 200, resp.text
    h = resp.headers
    return resp.text, int(h["X-Log-Offset"]), h["X-Log-Id"], int(h["X-Log-Start"]), h["X-Log-Reset"]


def _append(path, data: bytes):
    with open(path, "ab") as f:
        f.write(data)


def test_the_first_view_is_the_whole_file(log):
    client, path = log
    path.write_bytes(b"banner\n" + b"line\n" * 30_000)
    text, offset, _, start, reset = _view(client)
    assert (text.count("\n"), offset, start, reset) == (30_001, path.stat().st_size, 0, "1")


def test_a_poll_returns_only_the_lines_added_since(log):
    client, path = log
    path.write_bytes(b"banner\none\n")
    _, offset, log_id, _, _ = _view(client)
    _append(path, b"two\n")
    got = _view(client, offset, log_id)
    assert got == ("two\n", offset + 4, log_id, 0, "0")


def test_offset_zero_starts_over_even_with_the_current_id(log):
    client, path = log
    path.write_bytes(b"banner\none\n")
    _, _, log_id, _, _ = _view(client)
    got = _view(client, 0, log_id)
    assert got == ("banner\none\n", 11, log_id, 0, "1")


def test_a_line_still_being_written_waits_for_its_newline(log):
    client, path = log
    path.write_bytes(b"banner\none\ntw")
    text, offset, log_id, _, _ = _view(client)
    assert (text, offset) == ("banner\none\n", 11)
    got = _view(client, offset, log_id)
    assert got[0] == ""
    _append(path, b"o\n")
    got = _view(client, offset, log_id)
    assert got[:2] == ("two\n", 15)


def test_a_rotated_log_bigger_than_the_last_offset_starts_over(log):
    client, path = log
    path.write_bytes(b"2026-11-15 09:00 banner\nold\n")
    _, offset, log_id, _, _ = _view(client)
    os.rename(path, path.with_name("poster_renamerr.1.log"))
    path.write_bytes(b"2026-11-15 10:00 banner\n" + b"new\n" * 10)
    text, _, new_id, _, reset = _view(client, offset, log_id)
    assert (text, reset) == ("2026-11-15 10:00 banner\n" + "new\n" * 10, "1")
    assert new_id != log_id


def test_a_new_first_line_on_the_same_inode_starts_over(log):
    client, path = log
    path.write_bytes(b"2026-11-15 09:00 banner\nold\n")
    _, offset, log_id, _, _ = _view(client)
    with open(path, "r+b") as f:
        f.write(b"2026-11-15 10:00 banner\nnew line here\n")
    text, _, _, _, reset = _view(client, offset, log_id)
    assert (text, reset) == ("2026-11-15 10:00 banner\nnew line here\n", "1")


def test_a_truncated_log_starts_over(log):
    client, path = log
    path.write_bytes(b"banner\n" + b"line\n" * 10)
    _, offset, log_id, _, _ = _view(client)
    path.write_bytes(b"banner\n")
    got = _view(client, offset, log_id)
    assert got[0::4] == ("banner\n", "1")


def test_a_log_over_the_cap_shows_its_last_whole_lines(log, monkeypatch):
    client, path = log
    monkeypatch.setattr(logs, "VIEW_CAP", 18)
    path.write_bytes(b"banner\naaaa\nbbbb\ncccc\ndddd\n")
    text, offset, _, start, reset = _view(client)
    assert (text, start, offset, reset) == ("bbbb\ncccc\ndddd\n", 12, 27, "1")


def test_a_cut_that_lands_on_a_line_start_keeps_that_line(log, monkeypatch):
    client, path = log
    monkeypatch.setattr(logs, "VIEW_CAP", 15)
    path.write_bytes(b"banner\naaaa\nbbbb\ncccc\ndddd\n")
    got = _view(client)
    assert got[0] == "bbbb\ncccc\ndddd\n"


def test_a_view_grown_past_twice_the_cap_starts_over_at_the_end(log, monkeypatch):
    client, path = log
    path.write_bytes(b"banner\n")
    _, offset, log_id, _, _ = _view(client)
    monkeypatch.setattr(logs, "VIEW_CAP", 10)
    _append(path, b"aaaa\nbbbb\ncccc\n")
    text, _, _, start, reset = _view(client, offset, log_id)
    assert (text, start, reset) == ("bbbb\ncccc\n", 12, "1")


def test_a_view_within_twice_the_cap_of_its_start_keeps_appending(log, monkeypatch):
    client, path = log
    monkeypatch.setattr(logs, "VIEW_CAP", 10)
    path.write_bytes(b"banner\naaaa\nbbbb\ncccc\n")
    _, offset, log_id, start, _ = _view(client)
    _append(path, b"dddd\n")
    got = _view(client, offset, log_id, start)
    assert got == ("dddd\n", 27, log_id, 12, "0")


def test_offsets_count_bytes_across_non_ascii_lines(log):
    client, path = log
    path.write_bytes("banner\nkey ••••\n".encode())
    _, offset, log_id, _, _ = _view(client)
    _append(path, "après\n".encode())
    text, next_offset, _, _, _ = _view(client, offset, log_id)
    assert (text, next_offset) == ("après\n", path.stat().st_size)


def test_no_params_still_returns_the_raw_file_for_download(log):
    client, path = log
    path.write_bytes(b"banner\nline\nhalf")
    resp = client.get(URL)
    assert (resp.text, "X-Log-Offset" in resp.headers) == ("banner\nline\nhalf", False)


def test_an_overlong_id_is_refused(log):
    client, path = log
    path.write_bytes(b"banner\n")
    resp = client.get(URL, params={"offset": 7, "id": "x" * 65})
    assert resp.status_code == 422


def test_the_view_cap_holds_a_whole_log_at_the_default_rotation_size():
    from backend.util.logger import DEFAULT_MAX_LOG_BYTES

    assert logs.VIEW_CAP > DEFAULT_MAX_LOG_BYTES


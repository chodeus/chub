"""A write that got a server error is never sent again; reads and rate-limited writes are."""

import pytest

from backend.util import arr as arr_mod
from backend.util.arr import ARRTemporaryError, BaseARRClient, RetryHandler


class _Silent:
    def _noop(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = _noop


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.headers = {}
        self.text = ""
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _Session:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.methods = []

    def request(self, method, endpoint, **_kwargs):
        self.methods.append(method)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return _Response(status, {"id": 1})


def _client(monkeypatch, statuses):
    monkeypatch.setattr(arr_mod.time, "sleep", lambda _seconds: None)
    client = BaseARRClient.__new__(BaseARRClient)
    client.logger = _Silent()
    client.retry_handler = RetryHandler()
    client.session = _Session(statuses)
    client.timeout = 5
    return client


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("status", [500, 503])
def test_a_write_that_got_a_server_error_is_sent_once(monkeypatch, method, status):
    client = _client(monkeypatch, [status, 200])

    result = client._request_with_retries(method, "http://arr.test/api/v3/command")

    assert result is None
    assert client.session.methods == [method]


def test_a_read_that_got_a_server_error_is_tried_again(monkeypatch):
    client = _client(monkeypatch, [500, 200])

    result = client._request_with_retries("GET", "http://arr.test/api/v3/series")

    assert result == {"id": 1}
    assert client.session.methods == ["GET", "GET"]


def test_a_rate_limited_write_is_tried_again(monkeypatch):
    client = _client(monkeypatch, [429, 200])

    result = client._request_with_retries("POST", "http://arr.test/api/v3/command")

    assert result == {"id": 1}
    assert client.session.methods == ["POST", "POST"]


def test_retry_decisions_default_to_a_read():
    retry = RetryHandler().should_retry(0, ARRTemporaryError("Server error: 500"))

    assert retry is True

"""Pins LidarrClient.get_albums_by_id: repeated albumIds, chunking, and never an
empty request (Lidarr answers that with the whole library)."""

import json

import requests

from backend.util.arr import LidarrClient, RetryHandler


class _Silent:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _Recorder(requests.adapters.BaseAdapter):
    """A transport that records each URL requests built and answers with JSON."""

    def __init__(self, bodies):
        super().__init__()
        self.urls = []
        self.bodies = list(bodies)

    def send(self, request, **kwargs):
        self.urls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(self.bodies.pop(0)).encode()
        return response

    def close(self):
        pass


def _client(bodies):
    """A LidarrClient on the real request path, without the connect handshake."""
    client = LidarrClient.__new__(LidarrClient)
    client.url = "http://lidarr.test"
    client.logger = _Silent()
    client.retry_handler = RetryHandler()
    client.timeout = 5
    client.session = requests.Session()
    recorder = _Recorder(bodies)
    client.session.mount("http://", recorder)
    return client, recorder


def test_ids_go_out_as_repeated_album_ids_through_the_real_request_path():
    client, recorder = _client([[{"id": 5}, {"id": 3}]])

    albums = client.get_albums_by_id([5, 3, 5])

    assert albums == [{"id": 5}, {"id": 3}]
    assert recorder.urls == ["http://lidarr.test/api/v1/album?albumIds=5&albumIds=3"]


def test_ids_are_chunked_and_the_pages_joined():
    client, recorder = _client([[{"id": 1}, {"id": 2}], [{"id": 3}]])

    albums = client.get_albums_by_id([1, 2, 3], chunk=2)

    assert [album["id"] for album in albums] == [1, 2, 3]
    assert recorder.urls == [
        "http://lidarr.test/api/v1/album?albumIds=1&albumIds=2",
        "http://lidarr.test/api/v1/album?albumIds=3",
    ]


def test_no_ids_sends_no_request():
    client, recorder = _client([])

    albums = client.get_albums_by_id([])

    assert albums == []
    assert recorder.urls == []


def test_a_failed_chunk_fails_the_whole_lookup():
    """Half the albums would label half the imports; None lets the caller fall back."""
    client = LidarrClient.__new__(LidarrClient)
    client.url = "http://lidarr.test"
    pages = iter([[{"id": 1}], None])
    client.make_get_request = lambda endpoint, headers=None, params=None: next(pages)

    albums = client.get_albums_by_id([1, 2], chunk=1)

    assert albums is None

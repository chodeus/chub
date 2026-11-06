"""Pins Lidarr album lookups by id and the release dates the normalizer adds."""

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


def test_a_release_date_is_the_earliest_known_else_the_first_of_the_year():
    from backend.util.arr import first_release_date

    movie = {"inCinemas": "2020-05-01T00:00:00Z", "digitalRelease": "2020-03-01T00:00:00Z"}
    keys = ("inCinemas", "digitalRelease", "physicalRelease")
    assert first_release_date(movie, keys, 2020) == "2020-03-01"
    assert first_release_date({}, keys, 2019) == "2019-01-01"
    assert first_release_date({}, keys, None) is None
    assert first_release_date({}, keys, 0) is None


def test_normalized_movies_and_series_carry_their_release_date():
    from backend.util.arr import normalize_arr_media

    movie = normalize_arr_media(
        {"id": 1, "title": "M", "year": 2020, "path": "/m/M (2020)", "digitalRelease": "2020-03-01T00:00:00Z"},
        [],
        arr_type="radarr",
    )
    series = normalize_arr_media(
        {"id": 2, "title": "S", "year": 2015, "path": "/tv/S", "firstAired": "2015-09-15T00:00:00Z"},
        [],
        arr_type="sonarr",
    )

    assert movie["release_date"] == "2020-03-01"
    assert series["release_date"] == "2015-09-15"

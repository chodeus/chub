"""The *arr reads and commands renameinatorr's checks use, per client."""

import pytest

from backend.util.arr import (
    ARRAuthenticationError,
    ARRPermanentError,
    LidarrClient,
    RadarrClient,
    SonarrClient,
    normalize_arr_media,
)


class _Silent:
    def _noop(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = _noop


def _client(cls, responses):
    client = cls.__new__(cls)
    client.url = "http://arr.test"
    client.logger = _Silent()
    client.instance_name = "arr"
    client.headers = {}
    client.requests = []

    def fake_get(endpoint, headers=None, params=None):
        path = endpoint.removeprefix(client.api_base)
        client.requests.append((path, params))
        response = responses.get(path)
        if isinstance(response, Exception):
            raise response
        return response

    client.make_get_request = fake_get
    client.make_get_request_threadsafe = fake_get
    return client


@pytest.mark.parametrize(
    "cls, path",
    [(SonarrClient, "/series/13/folder"), (RadarrClient, "/movie/13/folder")],
)
def test_reads_the_folder_name_the_naming_format_gives(cls, path):
    client = _client(cls, {path: {"folder": "Show (2011)"}})

    folder = client.get_expected_folder({"media_id": 13}, threadsafe=True)

    assert folder == "Show (2011)"


@pytest.mark.parametrize(
    "response, expected",
    [
        (None, None),
        ("<html>", None),
        ({"folder": 7}, ""),
        (ARRPermanentError("404"), ""),
    ],
)
@pytest.mark.parametrize(
    "cls, path",
    [(SonarrClient, "/series/13/folder"), (RadarrClient, "/movie/13/folder")],
)
def test_an_unreadable_folder_name_is_none_and_a_missing_one_empty(
    cls, path, response, expected
):
    client = _client(cls, {path: response})

    folder = client.get_expected_folder({"media_id": 13})

    assert folder == expected


def _artist(media_id, folder):
    return {"id": media_id, "artistName": "Artist", "folder": folder}


def test_lidarr_reads_the_artist_folder_from_a_library_lookup():
    client = _client(LidarrClient, {"/artist/lookup": [_artist(13, "Artist (UK)")]})

    folder = client.get_expected_folder({"media_id": 13, "musicbrainz_id": "mb-1"})

    assert folder == "Artist (UK)"
    assert client.requests == [("/artist/lookup", {"term": "lidarr:mb-1"})]
    assert client.api_base.endswith("/api/v1")


@pytest.mark.parametrize(
    "response, expected",
    [
        ([], ""),
        ([_artist(99, "Someone Else")], ""),
        ([_artist(13, "A"), _artist(13, "B")], ""),
        (ARRPermanentError("404"), ""),
        (None, None),
    ],
)
def test_lidarr_gives_no_folder_unless_the_lookup_returns_that_artist(
    response, expected
):
    client = _client(LidarrClient, {"/artist/lookup": response})

    folder = client.get_expected_folder({"media_id": 13, "musicbrainz_id": "mb-1"})

    assert folder == expected


def test_lidarr_without_a_musicbrainz_id_does_not_look_up():
    client = _client(LidarrClient, {})

    folder = client.get_expected_folder({"media_id": 13, "musicbrainz_id": None})

    assert folder == ""
    assert client.requests == []


def test_media_files_come_back_relative_to_the_folder():
    sonarr = _client(
        SonarrClient,
        {
            "/filesystem/mediafiles": [
                {"path": "/tv/Show/Season 01/a.mkv", "relativePath": "Season 01/a.mkv"}
            ]
        },
    )
    lidarr = _client(
        LidarrClient,
        {
            "/filesystem/mediafiles": [
                {"path": "/music/Artist/Album/01.flac", "name": "01.flac"}
            ]
        },
    )

    sonarr_files = sonarr.get_media_files("/tv/Show")
    lidarr_files = lidarr.get_media_files("/music/Artist")

    assert sonarr_files == {"Season 01/a.mkv"}
    assert lidarr_files == {"Album/01.flac"}
    assert sonarr.requests == [("/filesystem/mediafiles", {"path": "/tv/Show"})]


def test_unreadable_media_files_are_none():
    client = _client(SonarrClient, {"/filesystem/mediafiles": "<html>"})

    files = client.get_media_files("/tv/Show")

    assert files is None


@pytest.mark.parametrize(
    "cls, endpoint, field, record",
    [
        (
            SonarrClient,
            "/episodefile",
            "seriesId",
            {"id": 5, "relativePath": "Season 01/a.mkv"},
        ),
        (
            RadarrClient,
            "/moviefile",
            "movieId",
            {"id": 5, "relativePath": "Season 01/a.mkv"},
        ),
        (
            LidarrClient,
            "/trackfile",
            "artistId",
            {"id": 5, "path": "/media/Show/Season 01/a.mkv"},
        ),
    ],
)
def test_file_records_come_back_relative_to_the_folder(cls, endpoint, field, record):
    client = _client(cls, {endpoint: [record]})

    records = client.get_file_records(13, "/media/Show")

    assert records == {5: "Season 01/a.mkv"}
    assert client.requests == [(endpoint, {field: 13})]


def test_unreadable_file_records_are_none():
    client = _client(LidarrClient, {"/trackfile": None})

    records = client.get_file_records(13, "/music/Artist")

    assert records is None


def test_lists_the_folders_inside_a_root_folder():
    client = _client(
        SonarrClient,
        {
            "/filesystem": {
                "directories": [{"name": "Show"}, {"name": "Other"}],
                "files": [],
            }
        },
    )

    folders = client.list_folders("/tv")

    assert folders == {"Show", "Other"}
    assert client.requests == [("/filesystem", {"path": "/tv/"})]


@pytest.mark.parametrize("response", [None, "<html>", {"files": []}])
def test_an_unreadable_listing_is_none(response):
    client = _client(SonarrClient, {"/filesystem": response})

    folders = client.list_folders("/tv")

    assert folders is None


def test_lidarr_renames_every_artist_in_one_command():
    client = _client(LidarrClient, {})
    posted = []
    client.make_post_request = lambda endpoint, json=None: (
        posted.append(json) or {"id": 2}
    )

    client.rename_media([13, 14])

    assert posted == [{"name": "RenameArtist", "artistIds": [13, 14]}]
    assert client.requests == []


@pytest.mark.parametrize("arr_type", ["radarr", "sonarr", "lidarr"])
def test_normalized_media_keeps_the_full_path(arr_type):
    item = {
        "id": 1,
        "title": "Show",
        "artistName": "Show",
        "path": "/media/Show (2011)",
    }

    normalized = normalize_arr_media(item, [], arr_type)

    assert normalized["path"] == "/media/Show (2011)"
    assert normalized["path_name"] == "Show (2011)"


_READS = [
    (lambda c: c.get_media_files("/tv/Show"), set()),
    (lambda c: c.list_folders("/tv"), None),
    (lambda c: c.get_file_records(13, "/tv/Show"), {}),
    (lambda c: c.get_expected_folder({"media_id": 13}), ""),
    (lambda c: c.get_rename_list(13, threadsafe=True), []),
]


def _refusing(error):
    client = _client(SonarrClient, {})

    def refuse(endpoint, headers=None, params=None):
        raise error

    client.make_get_request = refuse
    client.make_get_request_threadsafe = refuse
    return client


@pytest.mark.parametrize("read, missing", _READS)
def test_a_404_reads_as_nothing_there_not_a_crash(read, missing):
    result = read(_refusing(ARRPermanentError("404")))

    assert result == missing


@pytest.mark.parametrize("read, _missing", _READS)
def test_a_refused_key_reads_as_unreadable_not_a_crash(read, _missing):
    result = read(_refusing(ARRAuthenticationError("401")))

    assert result is None

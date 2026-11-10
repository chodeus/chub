"""Labelarr's ad-hoc sync writes tags only to the row's own *arr item, and says so when it can't."""

import contextlib
import json
from types import SimpleNamespace

import pytest
import requests

import backend.modules.labelarr as labelarr_mod
from backend.util.database import ChubDB


class _Logger:
    def debug(self, *a, **k):
        pass

    info = warning = error = debug

    def get_adapter(self, *_a, **_k):
        return self


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body
        self.headers, self.ok = {}, status < 400
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def arrs(monkeypatch):
    """The *arr HTTP side only: each host maps to the app it answers as."""
    state = SimpleNamespace(hosts={}, writes=[], put_status=None)

    def request(self, method, url, **kw):
        app = state.hosts[next(h for h in state.hosts if url.startswith(h))]
        if url.endswith("/system/status"):
            return _Resp(200, {"appName": app, "version": "5"})
        if url.endswith("/tag"):
            if method == "POST":
                return _Resp(201, {"id": 2, "label": kw["json"]["label"]})
            return _Resp(200, [{"id": 1, "label": "4k"}])
        if method == "PUT" and url.endswith("/editor"):
            if state.put_status:
                return _Resp(state.put_status)
            state.writes.append((url, kw["json"]))
            return _Resp(202, [{"id": 5}])
        return _Resp(404)

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr("backend.util.arr.time.sleep", lambda *_: None)
    return state


@pytest.fixture
def db(tmp_path, monkeypatch):
    with ChubDB(_Logger(), db_path=str(tmp_path / "chub.db")) as database:
        monkeypatch.setattr(
            labelarr_mod, "ChubDB", lambda logger=None: contextlib.nullcontext(database)
        )
        monkeypatch.setattr(
            database.plex,
            "get_by_id",
            lambda _id: {"id": 7, "instance_name": "plex_main", "title": "Item"},
        )
        yield database


@pytest.fixture
def plex(monkeypatch):
    synced = []

    class _Plex:
        def __init__(self, *a, **k):
            pass

        def is_connected(self):
            return True

        def current_labels(self, _item):
            return []

    monkeypatch.setattr(labelarr_mod, "PlexClient", _Plex)
    return synced


def named(**names):
    return {n: SimpleNamespace(url=u, api="k") for n, u in names.items()}


def _module(plex_synced):
    m = object.__new__(labelarr_mod.Labelarr)
    m._cancel_event = None
    m.config = SimpleNamespace(mappings=[], dry_run=False, log_level="info")
    m.full_config = SimpleNamespace(
        instances=SimpleNamespace(
            radarr=named(Main="http://r"),
            sonarr=named(Main="http://s"),
            lidarr=named(Music="http://l"),
            plex=named(plex_main="http://p"),
        )
    )
    m.logger = _Logger()
    m.sync_to_plex = lambda **kw: plex_synced.append(kw["plex_item"]["id"])
    return m


def _seed(db, title, asset_type, instance_type, instance_name, arr_id, season=None):
    item = {
        "title": title,
        "normalized_title": title.lower(),
        "year": 2020,
        "arr_id": arr_id,
        "tvdb_id": arr_id,
        "tmdb_id": arr_id,
        "season_number": season,
        "tags": ["old"],
        "plex_mapping_id": 7,
    }
    db.media.upsert(item, asset_type, instance_type, instance_name)
    query = "SELECT * FROM media_cache WHERE title=? AND instance_name=?"
    return db.media.execute_query(query, (title, instance_name), fetch_one=True)["id"]


def _sync(m, media_id, source_instance="Main", add=("4k",)):
    return m.labelarr_sync_adhoc(
        source_instance=source_instance,
        media_cache_id=media_id,
        tag_actions={"add": list(add), "remove": []},
        plex_instance="plex_main",
        plex_mapping_id=7,
    )


def _row(db, media_id):
    row = db.media.get_by_id(media_id)
    tags = row["tags"]
    return (
        (json.loads(tags) if isinstance(tags, str) else tags),
        row["source"],
        row["instance_name"],
    )


def test_a_series_tag_goes_to_its_own_sonarr_not_a_same_named_radarr(db, arrs, plex):
    arrs.hosts = {"http://r": "Radarr", "http://s": "Sonarr"}
    show = _seed(db, "Show", "show", "sonarr", "Main", 12)
    rows = len(db.media.get_all())

    result = _sync(_module(plex), show)

    assert result["success"] is True
    assert arrs.writes == [
        (
            "http://s/api/v3/series/editor",
            {"seriesIds": [12], "tags": [1], "applyTags": "add"},
        )
    ]
    assert _row(db, show) == (["old", "4k"], "sonarr", "Main")
    assert len(db.media.get_all()) == rows
    assert plex == [7]


@pytest.mark.parametrize(
    "seed, source_instance, code, message",
    [
        (
            ("Show", "show", "sonarr", "Main", 12, 0),
            "Main",
            "NOT_TAGGABLE",
            "Labelarr tags whole movies and series only",
        ),
        (
            ("Band", "artist", "lidarr", "Music", 3),
            "Music",
            "NOT_TAGGABLE",
            "Labelarr tags whole movies and series only",
        ),
        (
            ("Film", "movie", None, "Main", 4),
            "Main",
            "NOT_TAGGABLE",
            "The *arr type of 'Film' is not recorded; refresh the media cache and try again",
        ),
        (
            ("Film", "movie", "radarr", "Main", 4),
            "Other",
            "INSTANCE_MISMATCH",
            "Media item {id} belongs to Main, not Other",
        ),
    ],
    ids=["specials-season", "lidarr-artist", "type-not-recorded", "other-instance"],
)
def test_a_row_labelarr_must_not_tag_is_refused(
    db, arrs, plex, seed, source_instance, code, message
):
    arrs.hosts = {"http://r": "Radarr", "http://s": "Sonarr", "http://l": "Lidarr"}
    media_id = _seed(db, *seed)

    result = _sync(_module(plex), media_id, source_instance)

    assert (result["success"], result["error_code"]) == (False, code)
    assert result["message"] == message.format(id=media_id)
    assert arrs.writes == [] and plex == []
    assert _row(db, media_id)[0] == ["old"]


@pytest.mark.parametrize(
    "hosts, put_status, message",
    [
        (
            {"http://r": "Radarr"},
            503,
            "Tag sync for 'Film' failed: Main did not confirm adding 4k — see the server log",
        ),
        (
            {"http://r": "Sonarr"},
            None,
            "Tag sync for 'Film' failed: Main is not a Radarr instance",
        ),
    ],
    ids=["write-not-confirmed", "url-answers-as-another-app"],
)
def test_a_failed_tag_write_leaves_the_cache_and_plex_alone(
    db, arrs, plex, hosts, put_status, message
):
    arrs.hosts, arrs.put_status = hosts, put_status
    film = _seed(db, "Film", "movie", "radarr", "Main", 4)

    result = _sync(_module(plex), film)

    assert (result["success"], result["error_code"]) == (False, "ARR_TAG_WRITE_FAILED")
    assert result["message"] == message
    assert arrs.writes == [] and plex == []
    assert _row(db, film) == (["old"], "radarr", "Main")

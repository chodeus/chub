"""The media cache and Plex follow the tags the *arr really holds, through the real sync_to_plex."""

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


# Real *arr tag store: labels are lowercase, editor add/remove are set operations.
@pytest.fixture
def radarr(monkeypatch):
    st = SimpleNamespace(
        tags={9: "kids", 10: "a", 11: "b", 3: "old"},
        item_tags={4: {9, 3}},
        writes=[],
        on_put=None,
        fail_mode=None,
    )

    def request(self, method, url, **kw):
        if url.endswith("/system/status"):
            return _Resp(200, {"appName": "Radarr", "version": "5"})
        if url.endswith("/tag"):
            if method == "POST":
                new_id = max(st.tags) + 1
                st.tags[new_id] = kw["json"]["label"].lower()
                return _Resp(201, {"id": new_id, "label": st.tags[new_id]})
            return _Resp(200, [{"id": i, "label": lbl} for i, lbl in st.tags.items()])
        if method == "PUT" and url.endswith("/movie/editor"):
            body = kw["json"]
            if body["applyTags"] == st.fail_mode:
                return _Resp(503)
            st.writes.append((body["applyTags"], list(body["tags"])))
            for mid in body["movieIds"]:
                cur = st.item_tags.setdefault(mid, set())
                if body["applyTags"] == "add":
                    cur |= set(body["tags"])
                else:
                    cur -= set(body["tags"])
            hook, st.on_put = st.on_put, None
            if hook:
                hook()
            return _Resp(202, [{"id": 4}])
        return _Resp(404)

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr("backend.util.arr.time.sleep", lambda *_: None)
    return st


@pytest.fixture
def plex(monkeypatch):
    st = SimpleNamespace(labels=["Kids"], batch=[], upserts=[])

    class _Plex:
        def __init__(self, *a, **k):
            pass

        def is_connected(self):
            return True

        def current_labels(self, _item):
            return list(st.labels)

        def batch_update_labels(self, item, add, remove, dry_run):
            st.batch.append((list(add), list(remove)))

    monkeypatch.setattr(labelarr_mod, "PlexClient", _Plex)
    return st


@pytest.fixture
def db(tmp_path, monkeypatch, plex):
    with ChubDB(_Logger(), db_path=str(tmp_path / "chub.db")) as database:
        monkeypatch.setattr(
            labelarr_mod, "ChubDB", lambda logger=None: contextlib.nullcontext(database)
        )
        # The plex_cache row is a fake; its writes are recorded, not stored.
        monkeypatch.setattr(
            database.plex,
            "get_by_id",
            lambda _id: {
                "id": 7,
                "instance_name": "plex_main",
                "title": "Film",
                "year": 2020,
                "asset_type": "movie",
            },
        )
        monkeypatch.setattr(
            database.plex, "upsert", lambda row: plex.upserts.append(row)
        )
        yield database


def _module():
    m = object.__new__(labelarr_mod.Labelarr)
    m._cancel_event = None
    m.config = SimpleNamespace(mappings=[], dry_run=False, log_level="info")
    m.full_config = SimpleNamespace(
        instances=SimpleNamespace(
            radarr={"Main": SimpleNamespace(url="http://r", api="k")},
            sonarr={},
            lidarr={},
            plex={"plex_main": SimpleNamespace(url="http://p", api="k")},
        )
    )
    m.logger = _Logger()
    return m


def _seed_film(db, tags):
    item = {
        "title": "Film",
        "normalized_title": "film",
        "year": 2020,
        "arr_id": 4,
        "tmdb_id": 4,
        "tags": tags,
    }
    db.media.upsert(item, "movie", "radarr", "Main")
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title='Film'", fetch_one=True
    )
    db.media.execute_query(
        "UPDATE media_cache SET plex_mapping_id=7 WHERE id=?", (row["id"],)
    )
    return row["id"]


def _tags(db, media_id):
    raw = db.media.get_by_id(media_id)["tags"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _sync(m, media_id, add=(), remove=()):
    return m.labelarr_sync_adhoc(
        source_instance="Main",
        media_cache_id=media_id,
        tag_actions={"add": list(add), "remove": list(remove)},
        plex_instance="plex_main",
        plex_mapping_id=7,
    )


def test_removing_a_tag_named_in_other_case_updates_cache_and_plex(db, radarr, plex):
    film = _seed_film(db, ["kids", "old"])

    result = _sync(_module(), film, remove=["Kids"])

    assert radarr.item_tags[4] == {3}  # the *arr removed it (case-insensitive)
    assert result["success"] is True
    assert _tags(db, film) == ["old"]
    assert plex.batch == [([], ["Kids"])]
    assert result["data"]["changes"] == {"Kids": "remove"}


def test_adding_a_tag_named_in_other_case_keeps_one_lowercase_copy(db, radarr, plex):
    film = _seed_film(db, ["kids", "old"])

    result = _sync(_module(), film, add=["Old", "4K"])

    assert result["success"] is True
    assert _tags(db, film) == ["kids", "old", "4k"]


def test_overlapping_syncs_on_one_row_keep_both_tags_in_the_cache(db, radarr, plex):
    # Sync B runs inside sync A's *arr write, after A read the row.
    film = _seed_film(db, ["kids", "old"])
    m = _module()
    inner = []
    radarr.on_put = lambda: inner.append(_sync(m, film, add=["b"]))

    outer = _sync(m, film, add=["a"])

    assert outer["success"] and inner[0]["success"]
    assert {radarr.tags[i] for i in radarr.item_tags[4]} == {"kids", "old", "a", "b"}
    assert sorted(_tags(db, film)) == ["a", "b", "kids", "old"]


def test_a_one_item_bulk_sync_reports_what_landed(db, radarr, plex, monkeypatch):
    film = _seed_film(db, ["kids", "old"])
    radarr.fail_mode = "add"
    monkeypatch.setattr(labelarr_mod, "resync_media", lambda *a, **k: True)
    monkeypatch.setattr(
        "backend.util.connector.Connector",
        lambda **k: contextlib.nullcontext(
            SimpleNamespace(update_media_plex_mappings=lambda: None)
        ),
    )

    result = _module().labelarr_bulk_sync_adhoc(
        source_instance="Main",
        media_cache_ids=[film],
        tag_actions={"add": ["a"], "remove": ["old"]},
        plex_instance="plex_main",
        notify=False,
    )

    reason = (
        "Tag sync for 'Film' failed: Main removed old, but Main did not confirm "
        "adding a — see the server log"
    )
    assert radarr.writes == [("remove", [3])]
    assert (result["success"], result["message"]) == (False, reason)
    assert result["data"]["failures"] == [{"media_cache_id": film, "message": reason}]

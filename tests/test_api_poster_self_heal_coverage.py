"""GET /api/poster-self-heal/coverage — what the heal reports it will scan.

The panel this feeds must not disagree with the module's actual scope, so these
assert the WIDER heal semantics (a location claiming no types is still scanned)
rather than the maker's routing semantics.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import poster_self_heal as heal_router  # noqa: E402


class _Drive:
    def __init__(self, name, folder_id, types):
        self.name = name
        self.folder_id = folder_id
        self.types = types


class _Folder:
    def __init__(self, name, path, types):
        self.name = name
        self.path = path
        self.types = types


class _Cl2k:
    style = "CL2K"

    def __init__(self, local_folders, gdrive_uploads):
        self.local_folders = local_folders
        self.gdrive_uploads = gdrive_uploads


class _Cfg:
    def __init__(self, cl2k_maker):
        self.cl2k_maker = cl2k_maker


def _client(monkeypatch, cfg):
    """``cfg`` is a config object, or a zero-arg callable returning one (so a
    test can REPLACE the config between requests, not just mutate it)."""
    monkeypatch.setattr(heal_router, "load_config", cfg if callable(cfg) else lambda: cfg)
    app = FastAPI()
    app.include_router(heal_router.router)
    return TestClient(app)


def _routed_cfg():
    return _Cfg(
        _Cl2k(
            [
                _Folder("Posters", "/kometa/CL2K/Me", ["poster"]),
                _Folder("Logos", "/art/logos", ["logo"]),
            ],
            [
                _Drive("Posters", "POSTERS", ["poster"]),
                _Drive("Logos", "LOGOS", ["logo"]),
            ],
        )
    )


def test_coverage_lists_folders_and_drives(monkeypatch):
    resp = _client(monkeypatch, _routed_cfg()).get("/api/poster-self-heal/coverage")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert [f["path"] for f in data["folders"]] == ["/kometa/CL2K/Me", "/art/logos"]
    assert [d["folder_id"] for d in data["drives"]] == ["POSTERS", "LOGOS"]
    assert data["scanned_count"] == 2
    assert data["drive_count"] == 2


def test_coverage_reports_the_types_each_drive_actually_receives(monkeypatch):
    resp = _client(monkeypatch, _routed_cfg()).get("/api/poster-self-heal/coverage")
    by_id = {d["folder_id"]: d for d in resp.json()["data"]["drives"]}
    # LOGOS claims only "logo"; POSTERS is the fallback so it also receives the
    # types nobody claims — the panel must show what lands, not what's claimed.
    assert by_id["LOGOS"]["heals_types"] == ["logo"]
    assert by_id["POSTERS"]["heals_types"] == ["poster", "background", "squareart"]


def test_coverage_includes_a_folder_claiming_no_types(monkeypatch):
    """types:[] is inert for saving but still scanned — it must not be hidden."""
    cfg = _Cfg(_Cl2k([_Folder("Inert", "/art/orphans", [])], []))
    data = _client(monkeypatch, cfg).get("/api/poster-self-heal/coverage").json()["data"]
    assert [f["path"] for f in data["folders"]] == ["/art/orphans"]
    assert data["folders"][0]["types"] == []
    assert data["scanned_count"] == 1


def test_coverage_dedupes_drives_and_skips_blank_ids(monkeypatch):
    cfg = _Cfg(
        _Cl2k(
            [],
            [
                _Drive("Blank", "   ", ["logo"]),
                _Drive("A", "DUPE", ["logo"]),
                _Drive("B", "DUPE", ["background"]),
            ],
        )
    )
    data = _client(monkeypatch, cfg).get("/api/poster-self-heal/coverage").json()["data"]
    assert [d["folder_id"] for d in data["drives"]] == ["DUPE"]
    assert data["drive_count"] == 1


def test_coverage_flags_types_no_drive_receives(monkeypatch):
    cfg = _Cfg(_Cl2k([_Folder("Local only", "/art", ["logo"])], []))
    data = _client(monkeypatch, cfg).get("/api/poster-self-heal/coverage").json()["data"]
    # No Drive at all: nothing is renamed on Drive, so every type is unrouted.
    assert data["unrouted_types"] == ["poster", "logo", "background", "squareart"]
    assert data["drives"] == []


def test_coverage_without_the_cl2k_extension_is_empty_not_an_error(monkeypatch):
    data = _client(monkeypatch, _Cfg(None)).get("/api/poster-self-heal/coverage").json()
    assert data["data"] == {"available": False, "folders": [], "drives": []}


def test_coverage_rereads_config_each_request(monkeypatch):
    """Config is a live read — a settings save must not need a restart.

    The second config is a REPLACEMENT object, not a mutation of the first: a
    handler that captured the config once would still pass a mutation check,
    since it would be holding the very list being mutated.
    """
    holder = {"cfg": _routed_cfg()}
    client = _client(monkeypatch, lambda: holder["cfg"])
    assert client.get("/api/poster-self-heal/coverage").json()["data"]["drive_count"] == 2

    replaced = _routed_cfg()
    replaced.cl2k_maker.gdrive_uploads.append(_Drive("Backgrounds", "BGS", ["background"]))
    holder["cfg"] = replaced

    data = client.get("/api/poster-self-heal/coverage").json()["data"]
    assert data["drive_count"] == 3
    assert {d["folder_id"] for d in data["drives"]} == {"POSTERS", "LOGOS", "BGS"}


def test_coverage_collapses_duplicate_folder_paths(monkeypatch):
    """Two rows on one path are ONE scanned location — and the panel keys on path."""
    cfg = _Cfg(
        _Cl2k(
            [
                _Folder("First", "/art/shared", ["logo"]),
                _Folder("Second", "/art/shared", ["background"]),
                _Folder("Other", "/art/other", ["poster"]),
            ],
            [],
        )
    )
    data = _client(monkeypatch, cfg).get("/api/poster-self-heal/coverage").json()["data"]
    paths = [f["path"] for f in data["folders"]]
    assert paths == ["/art/shared", "/art/other"]
    assert len(paths) == len(set(paths))
    assert data["folders"][0]["name"] == "First"  # first claimer wins
    assert data["scanned_count"] == len(data["folders"])

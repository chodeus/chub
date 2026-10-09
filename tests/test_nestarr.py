"""Focused tests for Nestarr scanner and API safety behavior."""

import json
from types import SimpleNamespace

import pytest

from backend.api.nestarr import (
    FixRequest,
    _get_arr_client,
    _scan_nested_media_sync,
    _validate_target_path,
    get_cached_scan_results,
    router,
)
from backend.modules.nestarr import _NestScanner, nestarr_config_fingerprint
from backend.util.config import ChubConfig, InstanceDetail, NestarrConfig
from backend.util.database import ChubDB
from backend.util.notification_formatting import format_for_discord


class FakeCache:
    def __init__(self, rows=None, scan_row=None):
        self.rows = rows or []
        self.scan_row = scan_row
        self.queries = []

    def get_all(self):
        return self.rows

    def execute_query(self, query, params=None, fetch_one=False):
        self.queries.append({"query": query, "params": params, "fetch_one": fetch_one})
        normalized = query.strip().upper()
        if normalized.startswith("SELECT"):
            return (
                self.scan_row
                if fetch_one
                else ([self.scan_row] if self.scan_row else [])
            )
        if normalized.startswith("DELETE"):
            self.scan_row = None
            return None
        if normalized.startswith("INSERT"):
            self.scan_row = {"data": params[1], "scanned_at": params[2]}
            return None
        raise AssertionError(f"Unexpected query: {query}")


class FakeDB:
    def __init__(self, media_rows=None, plex_rows=None, scan_row=None):
        self.media = FakeCache(media_rows, scan_row=scan_row)
        self.plex = FakeCache(plex_rows)


def _response_payload(response):
    return json.loads(response.body.decode("utf-8"))


def _media_item(path, title, media_id, root="/data/media"):
    return {
        "media_id": media_id,
        "title": title,
        "year": 2024,
        "path": path,
        "root_folder": root,
        "instance_type": "radarr",
        "instance_name": "radarr_main",
        "has_file": True,
    }


MOVIES = [
    {
        "arr_instance": "radarr_main",
        "plex_instances": [{"instance": "plex_main", "library_names": ["Movies"]}],
    }
]


class _FakeArr:
    def __init__(self, media):
        self.media = media

    def is_connected(self):
        return True

    def get_media(self):
        return self.media


def _movie(arr_id, title, tmdb, has_file=True):
    return {
        "id": arr_id,
        "title": title,
        "year": 2024,
        "tmdbId": tmdb,
        "hasFile": has_file,
        "path": f"/data/movies/{title} (2024)",
        "rootFolderPath": "/data/movies",
    }


def _instances(*names):
    return SimpleNamespace(
        radarr={
            name: SimpleNamespace(enabled=True, url=f"http://{name}", api="key")
            for name in names
        },
        sonarr={},
        lidarr={},
    )


def _insert_plex(db, *, row_id, title, tmdb, library="Movies"):
    db.plex.execute_query(
        "INSERT INTO plex_media_cache (id, plex_id, instance_name, library_name, "
        "title, year, guids) VALUES (?, ?, 'plex_main', ?, ?, '2024', ?)",
        (row_id, str(5000 + row_id), library, title, json.dumps({"tmdb": str(tmdb)})),
    )


def _insert_media(db, *, row_id, arr_id, title, instance, plex_mapping_id=None):
    db.media.execute_query(
        "INSERT INTO media_cache (id, identity_key, asset_type, title, year, "
        "instance_name, source, folder, root_folder, arr_id, plex_mapping_id) "
        "VALUES (?, ?, 'movie', ?, '2024', ?, 'radarr', ?, '/data/movies', ?, ?)",
        (
            row_id,
            f"radarr|{instance}|{arr_id}",
            title,
            instance,
            f"{title} (2024)",
            arr_id,
            plex_mapping_id,
        ),
    )


def _unmatched(issues):
    return sorted(
        (issue["type"], issue["name"])
        for issue in issues
        if issue["type"] in ("arr_not_in_plex", "plex_not_in_arr")
    )


@pytest.fixture
def phase1(monkeypatch, tmp_path, stub_logger):
    """Real ChubDB, fake ARR pulls (arr[name] = media or None), recorded Plex walks."""
    state = SimpleNamespace(arr={}, walks=[], refreshed=None)

    def fake_walk(_db, _logger, libraries):
        state.walks.append(libraries)
        if isinstance(state.refreshed, Exception):
            raise state.refreshed
        if state.refreshed is not None:
            return state.refreshed
        return {(inst, lib) for inst, libs in libraries.items() for lib in libs}

    monkeypatch.setattr("backend.modules.nestarr.walk_plex_libraries", fake_walk)
    monkeypatch.setattr(
        "backend.modules.nestarr.create_arr_client",
        lambda url, api, _logger: _FakeArr(state.arr[url.split("//")[1]]),
    )
    monkeypatch.setattr("backend.util.connector.load_config", ChubConfig)
    with ChubDB(stub_logger, db_path=str(tmp_path / "chub.db"), quiet=True) as db:
        state.db = db
        yield state


def _scan(phase1, stub_logger, names=("radarr_main",), mappings=MOVIES):
    scanner = _NestScanner(
        _instances(*names), stub_logger, db=phase1.db, library_mappings=mappings
    )
    return scanner.scan(), scanner.warnings


def test_invalid_library_mapping_skips_unmatched_comparison(phase1, stub_logger):
    db = phase1.db
    _insert_plex(db, row_id=99, title="Mapped Movie", tmdb=101)
    config = NestarrConfig(
        library_mappings=[
            {"arr_instance": "radarr_main", "plex_instances": []},
        ]
    )
    phase1.arr["radarr_main"] = [_movie(10, "Mapped Movie", 101)]
    scanner = _NestScanner(
        _instances("radarr_main"),
        stub_logger,
        db=db,
        library_mappings=config.library_mappings,
    )

    issues = scanner.scan()

    assert _unmatched(issues) == []
    assert phase1.walks == []


def test_translate_path_uses_longest_boundary_matched_prefix(stub_logger):
    scanner = _NestScanner(
        None,
        stub_logger,
        path_mapping=[
            {"arr_path": "/data", "local_path": "/mnt/data"},
            {"arr_path": "/data/media", "local_path": "/mnt/media"},
        ],
    )

    assert scanner._translate_path("/data/media/movies") == "/mnt/media/movies"
    assert scanner._translate_path("/data/movies") == "/mnt/data/movies"
    assert scanner._translate_path("/data2/movies") == "/data2/movies"


def test_stray_scan_skips_items_without_root_folder(stub_logger):
    scanner = _NestScanner(None, stub_logger)
    issues = scanner._detect_stray_files(
        {
            "movie": [
                _media_item("/data/media/Parent/Child", "Child", 1, root=""),
            ]
        }
    )

    assert issues == []
    assert any("rootFolderPath" in msg for msg in stub_logger.messages["warning"])


def test_same_type_nesting_reports_nearest_parent_once(stub_logger):
    scanner = _NestScanner(None, stub_logger)
    issues = scanner._detect_nesting(
        [
            _media_item("/data/media/A", "A", 1),
            _media_item("/data/media/A/B", "B", 2),
            _media_item("/data/media/A/B/C", "C", 3),
        ],
        "movie",
    )

    assert len(issues) == 2
    parents_by_child = {issue["name"]: issue["parent"]["title"] for issue in issues}
    assert parents_by_child == {"B": "A", "C": "B"}
    assert len({issue["id"] for issue in issues}) == len(issues)


def test_cached_results_clear_stale_config_cache(monkeypatch, stub_logger):
    stale_config = NestarrConfig(instances=["old_radarr"])
    db = FakeDB(
        scan_row={
            "data": json.dumps(
                {
                    "issues": [{"id": "stale-issue"}],
                    "total": 1,
                    "instances_checked": ["old_radarr"],
                    "config_hash": nestarr_config_fingerprint(stale_config),
                }
            ),
            "scanned_at": "2026-01-01T00:00:00+00:00",
        }
    )
    current_config = ChubConfig()
    current_config.nestarr.instances = ["new_radarr"]
    monkeypatch.setattr("backend.api.nestarr.load_config", lambda: current_config)
    monkeypatch.setattr("backend.api.nestarr.get_module_logger", lambda *_: stub_logger)

    response = get_cached_scan_results(SimpleNamespace(), db)
    payload = _response_payload(response)

    assert payload["data"] == {
        "issues": [],
        "total": 0,
        "instances_checked": [],
        "scanned_at": None,
        "unmatched_enabled": False,
    }
    assert db.media.scan_row is None
    assert any(
        query["query"].strip().upper().startswith("DELETE")
        for query in db.media.queries
    )


def test_scan_sync_saves_config_hash_and_uses_legacy_instance_filter(
    monkeypatch, stub_logger
):
    config = ChubConfig()
    config.instances.radarr["radarr_main"] = InstanceDetail(
        url="http://radarr:7878", api="key"
    )
    config.instances.radarr["radarr_disabled"] = InstanceDetail(
        url="http://radarr-disabled:7878", api="key", enabled=False
    )
    config.nestarr.instances = ["radarr_main"]
    captured = {}

    def fake_scan_instances(_instances_config, _logger, **kwargs):
        captured.update(kwargs)
        return [{"id": "issue-1", "type": "movie_in_movie"}], ["check skipped"]

    monkeypatch.setattr("backend.api.nestarr.load_config", lambda: config)
    monkeypatch.setattr(
        "backend.api.nestarr.Nestarr.scan_instances",
        staticmethod(fake_scan_instances),
    )
    db = FakeDB()

    response = _scan_nested_media_sync(stub_logger, db)
    payload = _response_payload(response)
    saved_payload = json.loads(db.media.scan_row["data"])

    assert payload["data"]["total"] == 1
    assert captured["instance_filter"] == ["radarr_main"]
    assert captured["library_mappings"] is None
    assert saved_payload["issues"] == [{"id": "issue-1", "type": "movie_in_movie"}]
    assert saved_payload["instances_checked"] == ["radarr_main"]
    assert saved_payload["config_hash"] == nestarr_config_fingerprint(config.nestarr)
    assert payload["data"]["warnings"] == ["check skipped"]
    assert saved_payload["warnings"] == ["check skipped"]


def test_scan_route_prefers_post_and_keeps_legacy_get():
    methods_for_scan = [
        route.methods
        for route in router.routes
        if getattr(route, "path", None) == "/api/nestarr/scan"
    ]

    assert any("POST" in methods for methods in methods_for_scan)
    assert any("GET" in methods for methods in methods_for_scan)


def test_target_path_validation_rejects_client_supplied_arbitrary_path():
    body = FixRequest(
        instance_type="radarr",
        instance_name="radarr_main",
        media_id=1,
        target_path="/tmp/not-allowed",
    )
    raw_media = {
        "path": "/data/movies/Parent/Child",
        "rootFolderPath": "/data/movies",
    }

    target_path, response = _validate_target_path(raw_media, body)

    assert target_path is None
    assert response.status_code == 400


def test_target_path_validation_accepts_server_computed_target():
    body = FixRequest(
        instance_type="radarr",
        instance_name="radarr_main",
        media_id=1,
        target_path="/data/movies/Child",
    )
    raw_media = {
        "path": "/data/movies/Parent/Child",
        "rootFolderPath": "/data/movies",
    }

    target_path, response = _validate_target_path(raw_media, body)

    assert target_path == "/data/movies/Child"
    assert response is None


def test_get_arr_client_rejects_disabled_instances(monkeypatch, stub_logger):
    config = ChubConfig()
    config.instances.radarr["radarr_main"] = SimpleNamespace(
        url="http://radarr:7878",
        api="key",
        enabled=False,
    )
    monkeypatch.setattr(
        "backend.api.nestarr.create_arr_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not call")
        ),
    )

    app, response = _get_arr_client(
        config,
        FixRequest(
            instance_type="radarr",
            instance_name="radarr_main",
            media_id=1,
            target_path="/data/movies/Child",
        ),
        stub_logger,
    )

    assert app is None
    assert response.status_code == 400


def test_nestarr_notification_formatter_returns_fields():
    fields, success = format_for_discord(
        SimpleNamespace(module_name="nestarr"),
        [
            {
                "type": "movie_in_movie",
                "name": "Child",
                "year": 2024,
                "instance": "radarr_main",
                "path": "/data/movies/Parent/Child",
            }
        ],
    )

    assert success is True
    assert fields


def test_unmatched_scan_ignores_a_stale_stored_link(phase1, stub_logger):
    # The ARR row's stored link predates the item reaching Plex; the scan must not trust it.
    db = phase1.db
    _insert_media(db, row_id=1, arr_id=10, title="Some Movie", instance="radarr_main")
    _insert_plex(db, row_id=7, title="Some Movie", tmdb=101)
    phase1.arr["radarr_main"] = [_movie(10, "Some Movie", 101)]

    issues, warnings = _scan(phase1, stub_logger)

    assert _unmatched(issues) == []
    assert warnings == []
    assert phase1.walks == [{"plex_main": ["Movies"]}]


def test_unmatched_scan_reports_both_directions(phase1, stub_logger):
    db = phase1.db
    _insert_plex(db, row_id=7, title="Plex Only", tmdb=202)
    _insert_plex(db, row_id=8, title="In Both", tmdb=303)
    phase1.arr["radarr_main"] = [
        _movie(10, "Arr Only", 101),
        _movie(11, "In Both", 303),
        _movie(12, "Not Downloaded", 404, has_file=False),
    ]

    issues, _ = _scan(phase1, stub_logger)

    assert _unmatched(issues) == [
        ("arr_not_in_plex", "Arr Only"),
        ("plex_not_in_arr", "Plex Only"),
    ]


@pytest.mark.parametrize("walk", [set(), RuntimeError("plex down")])
def test_unmatched_scan_skips_a_library_the_walk_did_not_refresh(
    phase1, stub_logger, walk
):
    _insert_plex(phase1.db, row_id=7, title="Old Plex Row", tmdb=202)
    phase1.arr["radarr_main"] = [_movie(10, "Arr Only", 101)]
    phase1.refreshed = walk

    issues, warnings = _scan(phase1, stub_logger)

    assert _unmatched(issues) == []
    assert warnings == [
        "Unmatched check skipped for plex_main/Movies: Plex could not be refreshed."
    ]


def test_unmatched_scan_skips_a_library_whose_arr_pull_failed(phase1, stub_logger):
    _insert_plex(phase1.db, row_id=7, title="Owned By 4K", tmdb=202)
    phase1.arr["radarr_main"] = [_movie(10, "Arr Only", 101)]
    phase1.arr["radarr_4k"] = None
    mappings = MOVIES + [
        {
            "arr_instance": "radarr_4k",
            "plex_instances": [{"instance": "plex_main", "library_names": ["Movies"]}],
        }
    ]

    issues, warnings = _scan(
        phase1, stub_logger, names=("radarr_main", "radarr_4k"), mappings=mappings
    )

    assert _unmatched(issues) == []
    assert warnings == [
        "Unmatched check skipped for plex_main/Movies: radarr_4k could not be loaded."
    ]


def test_unmatched_scan_counts_links_of_instances_not_pulled_live(phase1, stub_logger):
    db = phase1.db
    _insert_plex(db, row_id=7, title="Owned By Unmapped", tmdb=202)
    _insert_plex(db, row_id=8, title="Owned By Nobody", tmdb=303)
    _insert_media(
        db, row_id=1, arr_id=20, title="Owned By Unmapped", instance="radarr_other",
        plex_mapping_id=7,
    )
    _insert_media(
        db, row_id=2, arr_id=21, title="Owned By Nobody", instance="radarr_main",
        plex_mapping_id=8,
    )
    phase1.arr["radarr_main"] = []

    issues, _ = _scan(phase1, stub_logger)

    # radarr_main was pulled live, so its stored link no longer counts
    assert _unmatched(issues) == [("plex_not_in_arr", "Owned By Nobody")]


def test_unmatched_scan_compares_only_the_refreshed_libraries(phase1, stub_logger):
    _insert_plex(phase1.db, row_id=7, title="Plex Only", tmdb=202)
    _insert_plex(phase1.db, row_id=8, title="Stale Kids Row", tmdb=303, library="Kids")
    phase1.arr["radarr_main"] = []
    phase1.refreshed = {("plex_main", "Movies")}
    mappings = [
        {
            "arr_instance": "radarr_main",
            "plex_instances": [
                {"instance": "plex_main", "library_names": ["Movies", "Kids"]}
            ],
        }
    ]

    issues, warnings = _scan(phase1, stub_logger, mappings=mappings)

    assert _unmatched(issues) == [("plex_not_in_arr", "Plex Only")]
    assert warnings == [
        "Unmatched check skipped for plex_main/Kids: Plex could not be refreshed."
    ]

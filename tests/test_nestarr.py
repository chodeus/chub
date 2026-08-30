"""Focused tests for Nestarr scanner and API safety behavior."""

import json
from types import SimpleNamespace

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


def test_invalid_library_mapping_falls_back_to_unmapped_comparison(stub_logger):
    db = FakeDB(
        media_rows=[
            {
                "id": 1,
                "arr_id": 10,
                "instance_name": "radarr_main",
                "source": "radarr",
                "title": "Mapped Movie",
                "plex_mapping_id": 99,
            }
        ],
        plex_rows=[
            {
                "id": 99,
                "instance_name": "plex_main",
                "library_name": "Movies",
                "title": "Mapped Movie",
            }
        ],
    )
    config = NestarrConfig(
        library_mappings=[
            {"arr_instance": "radarr_main", "plex_instances": []},
        ]
    )
    scanner = _NestScanner(
        None, stub_logger, db=db, library_mappings=config.library_mappings
    )

    issues = scanner._detect_unmatched(live_with_file={("radarr_main", 10)})

    assert issues == []


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
        return [{"id": "issue-1", "type": "movie_in_movie"}]

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

"""Focused tests for Nestarr scanner and API safety behavior."""

import json
import os
import unicodedata
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

    def get_movie_data(self, _movie_id):
        return []


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


# --- Phase 3: folder contents vs the ARR's file records ---


def _tracked(path, root, media_id=1, title="Some Title", file_paths=(), kind="radarr"):
    return {
        "media_id": media_id,
        "title": title,
        "year": 2024,
        "path": str(path),
        "root_folder": str(root),
        "instance_type": kind,
        "instance_name": f"{kind}_main",
        "has_file": True,
        "file_paths": None if file_paths is None else [str(p) for p in file_paths],
    }


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _file_issues(issues):
    return {
        issue["type"]: issue.get("video_files") or issue.get("missing_files")
        for issue in issues
        if issue["type"] in ("extra_video_in_folder", "missing_file")
    }


def test_file_check_flags_only_untracked_videos(stub_logger, tmp_path):
    root = tmp_path / "movies"
    folder = root / "Some Title (2024)"
    tracked = _touch(folder / "Some Title (2024).mkv")
    _touch(folder / "Some Title (2024) copy.mkv")
    for skipped in (
        "Featurettes/Making Of.mkv",
        "Some Title (2024)-trailer.mkv",
        "._Some Title (2024).mkv",
        ".hidden/Other.mkv",
        "Some Title (2024).nfo",
    ):
        _touch(folder / skipped)
    scanner = _NestScanner(None, stub_logger)

    issues = scanner._detect_stray_files(
        {"movie": [_tracked(folder, root, file_paths=[tracked])]}
    )

    assert _file_issues(issues) == {
        "extra_video_in_folder": ["Some Title (2024) copy.mkv"]
    }


def test_file_check_covers_series_and_missing_records(stub_logger, tmp_path):
    root = tmp_path / "tv"
    folder = root / "Some Show"
    first = _touch(folder / "Season 01" / "Some Show - S01E01.mkv")
    _touch(folder / "Season 01" / "Some Show - S01E02.mkv")
    gone = folder / "Season 01" / "Some Show - S01E03.mkv"
    scanner = _NestScanner(None, stub_logger)

    issues = scanner._detect_stray_files(
        {"series": [_tracked(folder, root, file_paths=[first, gone], kind="sonarr")]}
    )

    assert _file_issues(issues) == {
        "extra_video_in_folder": ["Season 01/Some Show - S01E02.mkv"],
        "missing_file": ["Season 01/Some Show - S01E03.mkv"],
    }


def test_file_check_matches_an_nfd_name_to_an_nfc_record(stub_logger, tmp_path):
    root = tmp_path / "movies"
    folder = root / "Cafe Film (2024)"
    _touch(folder / unicodedata.normalize("NFD", "Café Film (2024).mkv"))
    record = folder / unicodedata.normalize("NFC", "Café Film (2024).mkv")
    scanner = _NestScanner(None, stub_logger)

    issues = scanner._detect_stray_files(
        {"movie": [_tracked(folder, root, file_paths=[record])]}
    )

    assert _file_issues(issues) == {}


def test_file_check_skips_unknown_records(stub_logger, tmp_path):
    root = tmp_path / "movies"
    folder = root / "Some Title (2024)"
    _touch(folder / "Untracked.mkv")
    scanner = _NestScanner(None, stub_logger)

    issues = scanner._detect_stray_files(
        {"movie": [_tracked(folder, root, file_paths=None)]}
    )

    assert _file_issues(issues) == {}


def test_file_check_skips_a_folder_it_cannot_fully_read(
    monkeypatch, stub_logger, tmp_path
):
    root = tmp_path / "tv"
    folder = root / "Some Show"
    unreadable = folder / "Season 02"
    recorded = _touch(unreadable / "Some Show - S02E01.mkv")
    _touch(folder / "Season 01" / "Untracked.mkv")
    real_walk = os.walk

    def walk(top, onerror=None, **kwargs):
        # What os.walk does for a directory it cannot list (chmod 0 does not stop root)
        for dirpath, dirnames, filenames in real_walk(top, onerror=onerror, **kwargs):
            if dirpath == str(unreadable):
                onerror(PermissionError(13, "Permission denied", dirpath))
                continue
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", walk)
    scanner = _NestScanner(None, stub_logger)

    issues = scanner._detect_stray_files(
        {"series": [_tracked(folder, root, file_paths=[recorded], kind="sonarr")]}
    )

    assert _file_issues(issues) == {}
    assert scanner.warnings == [
        f"File check skipped for 1 folder(s) CHUB could not fully read, e.g. {folder}."
    ]


class _RecordsArr:
    def __init__(self):
        self.calls = []

    def get_movie_data(self, movie_id):
        self.calls.append(("movie", movie_id))
        return {3: [{"path": "/movies/C/C.mkv"}], 4: None}[movie_id]

    def get_episode_files_by_series(self, ids):
        self.calls.append(("series", ids))
        return {1: [{"path": "/tv/A/S01E01.mkv"}], 2: None}


def test_file_paths_by_item_reads_each_apps_records(stub_logger, tmp_path):
    for name in ("C", "D", "A", "B"):
        (tmp_path / name).mkdir()
    scanner = _NestScanner(None, stub_logger)
    radarr_app, sonarr_app = _RecordsArr(), _RecordsArr()

    radarr = scanner._file_paths_by_item(
        radarr_app,
        "radarr",
        [
            {"id": 1, "hasFile": True, "movieFile": {"path": "/movies/A/A.mkv"}},
            {"id": 2, "hasFile": False, "path": str(tmp_path / "none")},
            {"id": 3, "hasFile": True, "path": str(tmp_path / "C")},
            {"id": 4, "hasFile": True, "path": str(tmp_path / "D")},
            {"id": 5, "hasFile": True, "path": str(tmp_path / "unseen")},
        ],
    )
    sonarr = scanner._file_paths_by_item(
        sonarr_app,
        "sonarr",
        [
            {"id": 1, "path": str(tmp_path / "A")},
            {"id": 2, "path": str(tmp_path / "B")},
            {"id": 9, "path": str(tmp_path / "unseen")},
        ],
    )

    assert radarr == {1: ["/movies/A/A.mkv"], 2: [], 3: ["/movies/C/C.mkv"], 4: None}
    assert sonarr == {1: ["/tv/A/S01E01.mkv"], 2: None}
    # Folders CHUB cannot see get no request
    assert radarr_app.calls == [("movie", 3), ("movie", 4)]
    assert sonarr_app.calls == [("series", [1, 2])]
    lidarr = scanner._file_paths_by_item(_RecordsArr(), "lidarr", [{"id": 1}])
    assert lidarr == {}


def test_scan_warns_when_file_records_could_not_load(
    phase1, monkeypatch, stub_logger, tmp_path
):
    folder = tmp_path / "Some Movie (2024)"
    folder.mkdir()
    phase1.arr["radarr_main"] = [
        {
            "id": 10,
            "title": "Some Movie",
            "year": 2024,
            "hasFile": True,
            "path": str(folder),
            "rootFolderPath": str(tmp_path),
        }
    ]
    monkeypatch.setattr(_FakeArr, "get_movie_data", lambda self, _movie_id: None)
    scanner = _NestScanner(_instances("radarr_main"), stub_logger)

    scanner.scan()

    assert scanner.warnings == [
        "File check skipped for 1 item(s) in radarr_main: "
        "their file records could not be loaded."
    ]

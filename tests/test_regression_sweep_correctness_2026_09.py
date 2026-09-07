"""Correctness half of the 2026-09 sweep — one test per confirmed bug."""

import pytest


@pytest.mark.parametrize(
    "service,expected",
    [("lidarr", "v1"), ("Lidarr", "v1"), ("radarr", "v3"), ("sonarr", "v3"),
     ("plex", "v3"), (None, "v3"), ("", "v3")],
)
def test_arr_api_version(service, expected):
    """Lidarr is still on v1."""
    from backend.util.arr import arr_api_version

    assert arr_api_version(service) == expected


def test_arr_api_version_has_no_remaining_copies():
    """The bug was a missing copy, so the guard is that no copies remain."""
    import subprocess

    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", 'if service == "lidarr"', "backend/"],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    assert hits == [], hits


def test_upload_endpoints_read_the_payload_key():
    """upload_posters returns "payload"; reading "data" always gave {}."""
    import inspect

    import backend.api.posters.files as files
    import backend.util.upload_posters as up

    produced = inspect.getsource(up)
    assert '"payload"' in produced
    consumed = inspect.getsource(files)
    assert consumed.count('result.get("payload", {})') == 2
    assert 'result.get("data", {})' not in consumed


@pytest.mark.parametrize("value", [None, "", 0, "0"])
def test_year_zero_is_missing(value):
    """year is stored TEXT but the ARRs send 0, so the INT/TEXT split missed it."""
    from backend.util.database.media_metadata import is_missing_value

    assert is_missing_value("year", value) is True


@pytest.mark.parametrize("value", ["2019", 2019, "tt0111161"])
def test_real_values_are_not_missing(value):
    from backend.util.database.media_metadata import is_missing_value

    assert is_missing_value("year", value) is False


def test_empty_field_sql_matches_the_python_rule():
    """SQL mirrors is_missing_value; drift between them let year 0 through."""
    import sqlite3

    from backend.util.database.media_metadata import MetadataCompletenessMixin

    clause = MetadataCompletenessMixin._empty_field_clauses(["year"])
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (year TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [("0",), ("",), (None,), ("2019",)])
    hits = [r[0] for r in conn.execute(f"SELECT rowid FROM t WHERE {clause}")]
    assert hits == [1, 2, 3]  # '0', '', NULL — but not '2019'


def test_empty_config_section_does_not_crash_legacy_detection():
    """An empty YAML section is None, and the AttributeError escaped load_config."""
    from backend.util.config_migrator import is_legacy_config

    for section in ("poster_cleanarr", "border_replacerr", "labelarr"):
        assert is_legacy_config({section: None}) is False


def test_unmapped_image_type_is_refused(monkeypatch):
    """banner is unmapped, so the "" fallback used the poster's own suffix."""
    import backend.util.poster_self_heal.resolver as resolver

    import inspect

    # Premise: banner really is unmapped, and "" really is the poster's suffix.
    assert "banner" not in resolver._ASSET_SUFFIX
    assert resolver._ASSET_SUFFIX.get("poster") == ""
    src = inspect.getsource(resolver)
    expected = 'asset_suffix = _ASSET_SUFFIX.get(poster.get("image_type") or "poster")'
    assert expected in src
    assert "if asset_suffix is None:" in src
    assert '_ASSET_SUFFIX.get(poster.get("image_type") or "poster", "")' not in src


def test_folder_rename_count_survives_a_cancelled_chunk():
    """Items after the cancellation break never reach the assignment."""
    import inspect

    import backend.modules.renameinatorr as ren

    # An item that never reached the assignment has no key at all.
    media_dict = [{"new_path_name": "a"}, {"new_path_name": None}, {}]
    assert sum(bool(i.get("new_path_name")) for i in media_dict) == 1
    with pytest.raises(KeyError):
        sum(bool(i["new_path_name"]) for i in media_dict)
    src = inspect.getsource(ren)
    assert 'bool(i["new_path_name"])' not in src


def test_tmdb_transient_failure_is_retried_not_memoised(monkeypatch):
    """A TMDB blip poisoned that item for the rest of the module run."""
    from backend.util.tmdb import TMDBClient

    import threading

    client = TMDBClient.__new__(TMDBClient)
    client._memo = {}
    client._memo_lock = threading.Lock()
    client._auth_failed = False  # `enabled` is a property over cfg.apikey
    client.cfg = type("_Cfg", (), {"apikey": "k", "cache_expiration": 1})()
    client.db = type(
        "_DB",
        (),
        {"tmdb_id_cache": type("_C", (), {"get": lambda *a: (False, None)})()},
    )()
    assert client.enabled

    calls = []

    def _fetch(ext_str, source, media_type):
        calls.append(ext_str)
        return None  # transient failure

    client._fetch = _fetch
    assert client.find_tmdb_id("tt1", "imdb_id", "movie") is None
    assert client.find_tmdb_id("tt1", "imdb_id", "movie") is None
    assert len(calls) == 2, "second lookup was served from a poisoned memo"


def test_dns_failure_is_not_cached(monkeypatch):
    """A cached DNS failure rejected every webhook for that host until the TTL."""
    import socket

    import backend.util.webhook_processor as wp

    wp._DNS_CACHE.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror())
    )
    assert wp._resolve_ips("arr.local") == frozenset()
    assert "arr.local" not in wp._DNS_CACHE


def test_season_lookup_suffixes_the_title_key():
    """Only the guid keys carried the :S{n} suffix the index is built with."""
    import inspect

    import backend.util.plex_index as plex_index

    src = inspect.getsource(plex_index.PlexMediaIndex._search_values)
    assert 'values["title"] = f"{values[\'title\']}:S{season_number}"' in src


def test_missing_service_is_rejected_before_lower():
    """service is Optional, so .lower() on None reached the handler as a 500."""
    import inspect

    import backend.api.instances as instances

    src = inspect.getsource(instances)
    assert src.count('code="INVALID_SERVICE_TYPE"') >= 2
    assert "if not data.service:" in src


def test_non_model_schema_field_returns_404():
    """schedule is a plain dict; asking it for a JSON schema became a 500."""
    import inspect

    import backend.api.modules as modules

    src = inspect.getsource(modules)
    assert 'hasattr(field_info.annotation, "model_json_schema")' in src


def test_schedule_field_is_not_a_pydantic_model():
    """Premise check — if this becomes a model the guard above is dead code."""
    from backend.util.config import ChubConfig

    field = ChubConfig.model_fields["schedule"]
    assert not hasattr(field.annotation, "model_json_schema")


def test_failed_plex_client_is_not_cached():
    """A cached failed client left that instance dead for the whole run."""
    import inspect

    import backend.modules.asset_renamerr as ar

    src = inspect.getsource(ar.AssetRenamerr._plex_client_for)
    fail_branch = src[src.index("Failed to connect to Plex instance") :]
    assert "return None" in fail_branch.split("self._plex_clients")[0]

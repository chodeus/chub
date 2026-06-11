"""Tests for backend/modules/labelarr.py — tag/label parsing and instance map building."""

from types import SimpleNamespace


import backend.modules.labelarr as labelarr_mod
from backend.util.config import (
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    LabelarrMapping,
    LabelarrPlexInstance,
)


def make_module(config=None, full_config=None):
    m = object.__new__(labelarr_mod.Labelarr)
    m._cancel_event = None
    m.config = config or SimpleNamespace(mappings=[], dry_run=False)
    m.full_config = full_config or ChubConfig()
    return m


# --- _parse_tags / _parse_labels ---


def test_parse_tags_list_form():
    m = make_module()
    assert m._parse_tags(["a", "b"]) == ["a", "b"]


def test_parse_tags_filters_non_strings():
    m = make_module()
    assert m._parse_tags(["a", 1, "b", None]) == ["a", "b"]


def test_parse_tags_json_string():
    m = make_module()
    assert m._parse_tags('["x", "y"]') == ["x", "y"]


def test_parse_tags_invalid_json_returns_empty():
    m = make_module()
    assert m._parse_tags("not-json") == []


def test_parse_tags_other_types_return_empty():
    m = make_module()
    assert m._parse_tags(None) == []
    assert m._parse_tags(123) == []


def test_parse_tags_json_not_a_list_returns_empty():
    m = make_module()
    assert m._parse_tags('{"x": "y"}') == []


def test_parse_labels_delegates_to_tags():
    m = make_module()
    assert m._parse_labels(["a", "b"]) == ["a", "b"]


# --- _get_arr_config ---


def test_get_arr_config_finds_radarr():
    cfg = ChubConfig(
        instances=InstancesConfig(
            radarr={"r1": InstanceDetail(url="http://r:7878", api="k")},
        )
    )
    m = make_module(full_config=cfg)
    result = m._get_arr_config("r1")
    assert result is not None
    assert result.url == "http://r:7878"


def test_get_arr_config_finds_sonarr():
    cfg = ChubConfig(
        instances=InstancesConfig(
            sonarr={"s1": InstanceDetail(url="http://s", api="k")},
        )
    )
    m = make_module(full_config=cfg)
    assert m._get_arr_config("s1") is not None


def test_get_arr_config_returns_none_for_missing():
    m = make_module(full_config=ChubConfig())
    assert m._get_arr_config("not_there") is None


# --- _build_instance_map ---


def test_build_instance_map_arr_plus_plex():
    mappings = [
        LabelarrMapping(
            app_instance="radarr_main",
            plex_instances=[
                LabelarrPlexInstance(
                    instance="plex_main", library_names=["Movies", "Anime"]
                )
            ],
        )
    ]
    m = make_module(config=SimpleNamespace(mappings=mappings))
    result = m._build_instance_map()
    assert result["arrs"] == ["radarr_main"]
    assert result["plex"] == {"plex_main": ["Anime", "Movies"]}  # sorted


def test_build_instance_map_deduplicates_libraries():
    mappings = [
        LabelarrMapping(
            app_instance="radarr_main",
            plex_instances=[
                LabelarrPlexInstance(instance="plex_main", library_names=["X"]),
                LabelarrPlexInstance(instance="plex_main", library_names=["X", "Y"]),
            ],
        )
    ]
    m = make_module(config=SimpleNamespace(mappings=mappings))
    result = m._build_instance_map()
    assert result["plex"]["plex_main"] == ["X", "Y"]


def test_build_instance_map_empty_when_no_mappings():
    m = make_module(config=SimpleNamespace(mappings=[]))
    assert m._build_instance_map() == {}


def test_build_instance_map_skips_empty_plex_instance_name():
    mappings = [
        LabelarrMapping(
            app_instance="radarr_main",
            plex_instances=[LabelarrPlexInstance(instance="", library_names=["X"])],
        )
    ]
    m = make_module(config=SimpleNamespace(mappings=mappings))
    result = m._build_instance_map()
    assert "plex" not in result
    assert result["arrs"] == ["radarr_main"]


def test_build_instance_map_handles_dict_plex_entry():
    """plex_instances entries can also be dicts (unhydrated config)."""
    mappings = [
        SimpleNamespace(
            app_instance="radarr_main",
            plex_instances=[{"instance": "plex_main", "library_names": ["Movies"]}],
        )
    ]
    m = make_module(config=SimpleNamespace(mappings=mappings))
    result = m._build_instance_map()
    assert result["plex"]["plex_main"] == ["Movies"]


# --- run() / labelarr_sync_adhoc() instance validation and managed tag set ---


class _RecordingLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def warning(self, msg, *args, **kwargs):
        self.warnings.append(str(msg))

    def error(self, msg, *args, **kwargs):
        self.errors.append(str(msg))

    def log_outro(self):
        pass

    def get_adapter(self, name):
        return self


class _FakeTable:
    def __init__(self, rows=None):
        self._rows = {r["id"]: r for r in (rows or [])}

    def get_by_id(self, row_id):
        return self._rows.get(row_id)

    def get_all(self):
        return list(self._rows.values())

    def get_by_instance(self, name):
        return []

    def get_by_instance_and_library(self, instance, library):
        return []

    def upsert(self, *args, **kwargs):
        pass


class _FakeDB:
    def __init__(self, media_rows=None, plex_rows=None):
        self.media = _FakeTable(media_rows)
        self.plex = _FakeTable(plex_rows)

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnector:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update_arr_database(self):
        pass

    def update_media_plex_mappings(self):
        pass


def test_run_skips_unconfigured_plex_instance(monkeypatch):
    """A mapping referencing a missing Plex instance is skipped with a warning,
    not a KeyError that aborts the whole run."""
    import backend.util.plex_refresh as plex_refresh_mod

    mappings = [
        LabelarrMapping(
            app_instance="radarr_main",
            labels=["kids"],
            plex_instances=[
                LabelarrPlexInstance(instance="ghost", library_names=["Movies"])
            ],
        )
    ]
    m = make_module(
        config=SimpleNamespace(mappings=mappings, dry_run=False, log_level="info"),
        full_config=ChubConfig(instances=InstancesConfig(plex={})),
    )
    m.logger = _RecordingLogger()

    monkeypatch.setattr(labelarr_mod, "ChubDB", _FakeDB())
    monkeypatch.setattr(labelarr_mod, "Connector", _FakeConnector)
    monkeypatch.setattr(
        plex_refresh_mod, "refresh_plex_cache_if_stale", lambda *a, **k: None
    )

    m.run()

    assert any("ghost" in w for w in m.logger.warnings)
    assert m.logger.errors == []


def _adhoc_module(plex_instances):
    media_row = {
        "id": 1,
        "title": "Movie",
        "tags": ["existing", "unrelated"],
        "arr_id": None,
        "asset_type": "movie",
        "instance_type": "radarr",
        "plex_mapping_id": 7,
    }
    plex_row = {"id": 7, "instance_name": "plex_main", "asset_type": "movie"}
    m = make_module(
        config=SimpleNamespace(mappings=[], dry_run=False, log_level="info"),
        full_config=ChubConfig(instances=InstancesConfig(plex=plex_instances)),
    )
    m.logger = _RecordingLogger()
    return m, _FakeDB(media_rows=[media_row], plex_rows=[plex_row])


def test_adhoc_sync_unknown_plex_instance_returns_error(monkeypatch):

    m, db = _adhoc_module(plex_instances={})
    monkeypatch.setattr(labelarr_mod, "ChubDB", db)

    result = m.labelarr_sync_adhoc(
        source_instance="radarr_main",
        media_cache_id=1,
        tag_actions={"add": ["new-tag"], "remove": []},
        plex_instance="ghost",
        plex_mapping_id=7,
    )

    assert result["success"] is False
    assert result["error_code"] == "PLEX_INSTANCE_NOT_FOUND"


def test_adhoc_sync_manages_only_tag_action_tags(monkeypatch):
    """labels_lower passed to sync_to_plex must contain only the tags named in
    tag_actions — never the item's other tags (which run() would not manage)."""

    m, db = _adhoc_module(
        plex_instances={"plex_main": InstanceDetail(url="http://p", api="k")}
    )
    monkeypatch.setattr(labelarr_mod, "ChubDB", db)

    class _FakePlexClient:
        def __init__(self, *args, **kwargs):
            pass

        def is_connected(self):
            return True

    monkeypatch.setattr(labelarr_mod, "PlexClient", _FakePlexClient)

    captured = {}

    def fake_sync_to_plex(**kwargs):
        captured["labels_lower"] = kwargs["labels_lower"]
        return None

    m.sync_to_plex = fake_sync_to_plex

    result = m.labelarr_sync_adhoc(
        source_instance="radarr_main",
        media_cache_id=1,
        tag_actions={"add": ["new-tag"], "remove": ["existing"]},
        plex_instance="plex_main",
        plex_mapping_id=7,
        dry_run=True,
    )

    assert result["success"] is True
    assert captured["labels_lower"] == {
        "new-tag": "new-tag",
        "existing": "existing",
    }
    # The item's unmanaged tag must not be synced.
    assert "unrelated" not in captured["labels_lower"]

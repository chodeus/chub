"""Tests for backend/modules/labelarr.py — tag/label parsing and instance map building."""

from types import SimpleNamespace

import pytest

from backend.modules.labelarr import Labelarr
from backend.util.config import (
    ChubConfig,
    InstanceDetail,
    InstancesConfig,
    LabelarrMapping,
    LabelarrPlexInstance,
)


def make_module(config=None, full_config=None):
    m = object.__new__(Labelarr)
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

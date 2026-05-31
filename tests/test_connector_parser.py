"""Tests for backend/util/connector.py — InstanceParser parsing logic."""

from types import SimpleNamespace

import pytest

from backend.util.config import ChubConfig, InstanceDetail, InstancesConfig
from backend.util.connector import (
    InstanceConfigError,
    InstanceParser,
    build_instance_map,
    gather_media_and_collections,
)


def make_config():
    return ChubConfig(
        instances=InstancesConfig(
            radarr={"radarr_main": InstanceDetail(url="http://r:7878", api="rk")},
            sonarr={"sonarr_main": InstanceDetail(url="http://s:8989", api="sk")},
            plex={"plex_main": InstanceDetail(url="http://p:32400", api="pt")},
        )
    )


# --- _parse_arr_instances ---


def test_parse_arr_resolves_radarr():
    cfg = make_config()
    result = InstanceParser._parse_arr_instances(["radarr_main"], cfg)
    assert len(result) == 1
    assert result[0].name == "radarr_main"
    assert result[0].type == "radarr"
    assert result[0].url == "http://r:7878"


def test_parse_arr_resolves_sonarr():
    cfg = make_config()
    result = InstanceParser._parse_arr_instances(["sonarr_main"], cfg)
    assert result[0].type == "sonarr"


def test_parse_arr_unknown_raises():
    cfg = make_config()
    with pytest.raises(InstanceConfigError):
        InstanceParser._parse_arr_instances(["missing"], cfg)


def test_parse_arr_missing_credentials_raises():
    cfg = ChubConfig(
        instances=InstancesConfig(
            radarr={"r1": InstanceDetail(url="", api="")},
        ),
    )
    with pytest.raises(InstanceConfigError):
        InstanceParser._parse_arr_instances(["r1"], cfg)


def test_parse_arr_disabled_instance_skipped():
    cfg = ChubConfig(
        instances=InstancesConfig(
            radarr={"r1": InstanceDetail(url="http://r", api="k", enabled=False)},
        ),
    )
    result = InstanceParser._parse_arr_instances(["r1"], cfg)
    assert result == []


# --- _parse_plex_instances ---


def test_parse_plex_simple_list_form():
    cfg = make_config()
    result = InstanceParser._parse_plex_instances(
        {"plex_main": ["Movies", "Shows"]}, cfg
    )
    assert len(result) == 1
    assert result[0].libraries == ["Movies", "Shows"]


def test_parse_plex_dict_form():
    cfg = make_config()
    result = InstanceParser._parse_plex_instances(
        {"plex_main": {"library_names": ["Movies"]}}, cfg
    )
    assert result[0].libraries == ["Movies"]


def test_parse_plex_unknown_instance_raises():
    cfg = make_config()
    with pytest.raises(InstanceConfigError):
        InstanceParser._parse_plex_instances({"nope": ["X"]}, cfg)


def test_parse_plex_invalid_format_raises():
    cfg = make_config()
    with pytest.raises(InstanceConfigError):
        InstanceParser._parse_plex_instances({"plex_main": "string-not-allowed"}, cfg)


def test_parse_plex_missing_credentials_raises():
    cfg = ChubConfig(
        instances=InstancesConfig(plex={"p1": InstanceDetail(url="", api="")}),
    )
    with pytest.raises(InstanceConfigError):
        InstanceParser._parse_plex_instances({"p1": ["x"]}, cfg)


# --- parse_instance_map (top-level) ---


def test_parse_instance_map_both_kinds():
    cfg = make_config()
    out = InstanceParser.parse_instance_map(
        {"arrs": ["radarr_main"], "plex": {"plex_main": ["Movies"]}}, cfg
    )
    assert len(out["arr"]) == 1
    assert len(out["plex"]) == 1


def test_parse_instance_map_arrs_only():
    cfg = make_config()
    out = InstanceParser.parse_instance_map({"arrs": ["radarr_main"]}, cfg)
    assert len(out["arr"]) == 1
    assert out["plex"] == []


def test_parse_instance_map_empty():
    cfg = make_config()
    out = InstanceParser.parse_instance_map({}, cfg)
    assert out == {"arr": [], "plex": []}


# --- shared media-gathering / instance-map helpers ---


def test_build_instance_map_splits_arrs_and_plex():
    cfg = SimpleNamespace(
        instances=[
            "radarr_main",
            "sonarr_main",
            {"plex_main": SimpleNamespace(library_names=["Movies", "TV"])},
        ]
    )
    m = build_instance_map(cfg)
    assert m["arrs"] == ["radarr_main", "sonarr_main"]
    assert m["plex"] == {"plex_main": ["Movies", "TV"]}


def test_gather_media_and_collections_merges_media_and_collections():
    cfg = SimpleNamespace(
        instances=[
            "radarr_main",
            {"plex_main": SimpleNamespace(library_names=["Movies"])},
        ]
    )

    class FakeMedia:
        def get_by_instance(self, name):
            return [{"id": 1}] if name == "radarr_main" else []

    class FakeColl:
        def get_by_instance_and_library(self, inst, lib):
            return [{"id": 2}]

    db = SimpleNamespace(media=FakeMedia(), collection=FakeColl())
    rows = gather_media_and_collections(cfg, db)
    assert sorted(r["id"] for r in rows) == [1, 2]

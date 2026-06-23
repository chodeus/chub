"""Tests for the legacy-config auto-migrator.

Each rule gets its own test plus an idempotency check at the end. The
fixture below builds a maximally-legacy config blob that triggers every
rule; we then assert the migrated output and run the migrator again to
confirm a second pass produces no further changes.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.config_migrator import is_legacy_config, migrate  # noqa: E402


def _legacy_blob():
    """A config that exercises every migration rule."""
    return {
        "main": {
            "log_level": "INFO",
            "theme": "dark",
            "update_notifications": False,
        },
        "discord": {"webhook": "https://example.com/x"},
        "poster_renamerr": {
            "dry_run": False,
            "incremental_border_replacerr": True,
            "source_dirs": ["/posters"],
        },
        "unmatched_assets": {
            "log_level": "info",
            "ignore_root_folders": ["/mnt/junk"],
            "source_dirs": ["/posters"],
            "instances": [
                "radarr",
                "sonarr",
                {"Plex": {"library_names": ["Movies", "TV Shows"]}},
            ],
        },
        "renameinatorr": {
            "ignore_tag": "do-not-touch",
        },
        "poster_cleanarr": {
            "dry_run": True,
            "source_dirs": ["/posters"],
            "ignore_media": ["Some Title"],
        },
        "border_replacerr": {
            "holidays": {
                "christmas": {"schedule": "12-01/12-26", "color": "#ff0000"},
                "halloween": {"schedule": "10-25/10-31", "color": ["#ff8800"]},
            },
        },
        "labelarr": {
            "mappings": [
                {
                    "app_instance": "radarr",
                    "labels": ["lbl"],
                    "plex_instances": [
                        {"plex_instance": "plex_1", "library_names": ["Movies"]},
                    ],
                }
            ]
        },
    }


# ─── Detection heuristic ────────────────────────────────────────────────


def test_detection_chub_native_is_false():
    chub_native = {
        "general": {"log_level": "info"},
        "user_interface": {"theme": "dark"},
        "poster_renamerr": {"dry_run": False, "source_dirs": ["/posters"]},
    }
    assert is_legacy_config(chub_native) is False


def test_detection_empty_is_false():
    assert is_legacy_config({}) is False


def test_detection_non_dict_is_false():
    assert is_legacy_config("not a config") is False  # type: ignore[arg-type]


def test_detection_main_section_triggers():
    assert is_legacy_config({"main": {"theme": "dark"}}) is True


def test_detection_discord_section_triggers():
    assert is_legacy_config({"discord": {}}) is True


def test_detection_legacy_nested_key_triggers():
    assert is_legacy_config({"unmatched_assets": {"ignore_root_folders": []}}) is True


def test_detection_cleanarr_dry_run_bool_triggers():
    assert is_legacy_config({"poster_cleanarr": {"dry_run": True}}) is True


def test_detection_cleanarr_mode_string_is_chub_native():
    assert is_legacy_config({"poster_cleanarr": {"mode": "report"}}) is False


def test_detection_holidays_dict_triggers():
    assert is_legacy_config({"border_replacerr": {"holidays": {"x": {}}}}) is True


def test_detection_holidays_list_is_chub_native():
    assert is_legacy_config({"border_replacerr": {"holidays": []}}) is False


def test_detection_unmatched_instances_dict_entry_triggers_split():
    # A dict entry in instances is the legacy shape — it must trigger migration
    # so the split rule converts it into plex_scope.
    assert (
        is_legacy_config({"unmatched_assets": {"instances": ["radarr", {"Plex": {}}]}})
        is True
    )


def test_detection_unmatched_instances_all_strings_is_chub_native():
    assert (
        is_legacy_config({"unmatched_assets": {"instances": ["radarr", "sonarr"]}})
        is False
    )


# ─── Individual rules ───────────────────────────────────────────────────


def test_rule_move_main_log_level_lowercases():
    out, _ = migrate({"main": {"log_level": "INFO"}})
    assert out["general"]["log_level"] == "info"
    assert "main" not in out


def test_rule_move_main_theme():
    out, _ = migrate({"main": {"theme": "dark"}})
    assert out["user_interface"]["theme"] == "dark"


def test_rule_move_main_update_notifications():
    out, _ = migrate({"main": {"update_notifications": True}})
    assert out["general"]["update_notifications"] is True


def test_rule_drop_main_section_after_moves():
    out, _ = migrate({"main": {"log_level": "info", "extra": "ignored"}})
    assert "main" not in out


def test_rule_drop_discord_section():
    out, notes = migrate({"discord": {"webhook": "x"}})
    assert "discord" not in out
    assert any(n.rule == "drop-section:discord" for n in notes)


def test_rule_rename_ignore_root_folders():
    out, _ = migrate({"unmatched_assets": {"ignore_root_folders": ["/x"]}})
    assert out["unmatched_assets"]["ignore_folders"] == ["/x"]
    assert "ignore_root_folders" not in out["unmatched_assets"]


def test_rule_rename_ignore_tag():
    out, _ = migrate({"renameinatorr": {"ignore_tag": "skip"}})
    assert out["renameinatorr"]["ignore_tags"] == "skip"


def test_rule_rename_source_dirs_in_poster_cleanarr():
    out, _ = migrate({"poster_cleanarr": {"source_dirs": ["/p"]}})
    assert out["poster_cleanarr"]["asset_dirs"] == ["/p"]
    assert "source_dirs" not in out["poster_cleanarr"]


def test_rule_rename_labelarr_plex_instance_to_instance():
    out, _ = migrate(
        {
            "labelarr": {
                "mappings": [
                    {
                        "plex_instances": [
                            {"plex_instance": "p1", "library_names": ["M"]},
                            {"plex_instance": "p2", "library_names": ["T"]},
                        ]
                    }
                ]
            }
        }
    )
    entries = out["labelarr"]["mappings"][0]["plex_instances"]
    assert entries[0]["instance"] == "p1"
    assert entries[1]["instance"] == "p2"
    assert all("plex_instance" not in e for e in entries)


def test_rule_drop_incremental_border_replacerr():
    out, _ = migrate({"poster_renamerr": {"incremental_border_replacerr": True}})
    assert "incremental_border_replacerr" not in out["poster_renamerr"]


def test_rule_drop_unmatched_source_dirs():
    out, _ = migrate({"unmatched_assets": {"source_dirs": ["/p"]}})
    assert "source_dirs" not in out["unmatched_assets"]


def test_rule_drop_cleanarr_ignore_media():
    out, _ = migrate({"poster_cleanarr": {"ignore_media": ["X"]}})
    assert "ignore_media" not in out["poster_cleanarr"]


def test_rule_cleanarr_dry_run_true_becomes_report():
    out, _ = migrate({"poster_cleanarr": {"dry_run": True}})
    assert out["poster_cleanarr"]["mode"] == "report"
    assert "dry_run" not in out["poster_cleanarr"]


def test_rule_cleanarr_dry_run_false_becomes_remove():
    out, _ = migrate({"poster_cleanarr": {"dry_run": False}})
    assert out["poster_cleanarr"]["mode"] == "remove"


def test_rule_cleanarr_existing_mode_wins():
    out, _ = migrate({"poster_cleanarr": {"dry_run": True, "mode": "move"}})
    assert out["poster_cleanarr"]["mode"] == "move"
    assert "dry_run" not in out["poster_cleanarr"]


def test_split_poster_renamerr_instances_to_plex_scope():
    raw = {
        "main": {"theme": "dark"},  # forces migration via an existing legacy signal
        "poster_renamerr": {
            "instances": [
                "Radarr",
                {"Plex": {"library_names": ["Movies"], "add_posters": True}},
            ]
        },
    }
    out, notes = migrate(raw)
    assert out["poster_renamerr"]["instances"] == ["Radarr"]
    assert out["poster_renamerr"]["plex_scope"] == [
        {
            "instance": "Plex",
            "library_names": ["Movies"],
            "add_posters": True,
            "match_collections": True,
        }
    ]
    assert any("plex_scope" in n.rule for n in notes)


def test_split_asset_renamerr_instances_to_plex_scope():
    raw = {
        "main": {"theme": "dark"},
        "asset_renamerr": {
            "instances": [
                "Radarr",
                {"Plex": {"library_names": ["Movies"], "add_posters": True}},
            ]
        },
    }
    out, notes = migrate(raw)
    assert out["asset_renamerr"]["instances"] == ["Radarr"]
    assert out["asset_renamerr"]["plex_scope"] == [
        {
            "instance": "Plex",
            "library_names": ["Movies"],
            "add_posters": True,
            "match_collections": True,
        }
    ]
    assert any("plex_scope" in n.rule for n in notes)


def test_split_poster_renamerr_empty_libs_preserves_no_collections():
    raw = {
        "main": {"theme": "dark"},
        "poster_renamerr": {
            "instances": [
                "Radarr",
                {"Plex": {"library_names": [], "add_posters": True}},
            ]
        },
    }
    out, _ = migrate(raw)
    scope = out["poster_renamerr"]["plex_scope"][0]
    assert scope["match_collections"] is False
    assert scope["add_posters"] is True


def test_split_unmatched_instances_to_plex_scope():
    raw = {
        "main": {"theme": "dark"},
        "unmatched_assets": {
            "instances": ["Radarr", {"Plex": {"library_names": ["Movies", "Anime"]}}]
        },
    }
    out, _ = migrate(raw)
    assert out["unmatched_assets"]["instances"] == ["Radarr"]
    assert out["unmatched_assets"]["plex_scope"] == [
        {
            "instance": "Plex",
            "library_names": ["Movies", "Anime"],
            "add_posters": False,
            "match_collections": True,
        }
    ]


def test_split_is_idempotent_on_new_shape():
    raw = {
        "poster_renamerr": {
            "instances": ["Radarr"],
            "plex_scope": [
                {
                    "instance": "Plex",
                    "library_names": ["Movies"],
                    "add_posters": True,
                    "match_collections": True,
                }
            ],
        }
    }
    assert is_legacy_config(raw) is False
    out, notes = migrate(raw)
    assert out["poster_renamerr"]["plex_scope"] == raw["poster_renamerr"]["plex_scope"]
    assert not any("plex_scope" in n.rule for n in notes)


def test_unmatched_dict_form_migrates_into_plex_scope():
    raw = {
        "main": {"theme": "dark"},
        "unmatched_assets": {
            "instances": ["radarr", "sonarr", {"Plex": {"library_names": ["Movies"]}}]
        },
    }
    out, notes = migrate(raw)
    assert out["unmatched_assets"]["instances"] == ["radarr", "sonarr"]
    assert out["unmatched_assets"]["plex_scope"][0]["instance"] == "Plex"
    assert any("plex_scope" in n.rule for n in notes)


def test_rule_holidays_dict_to_list_single_string_color():
    out, _ = migrate(
        {
            "border_replacerr": {
                "holidays": {"christmas": {"schedule": "12-01/12-26", "color": "#f00"}}
            }
        }
    )
    holidays = out["border_replacerr"]["holidays"]
    assert isinstance(holidays, list)
    assert holidays[0]["name"] == "christmas"
    assert holidays[0]["schedule"] == "12-01/12-26"
    assert holidays[0]["colors"] == ["#f00"]
    assert holidays[0]["borders"] == []


def test_rule_holidays_dict_to_list_list_color():
    out, _ = migrate(
        {
            "border_replacerr": {
                "holidays": {
                    "halloween": {
                        "schedule": "10-25/10-31",
                        "color": ["#f80", "#000"],
                    }
                }
            }
        }
    )
    assert out["border_replacerr"]["holidays"][0]["colors"] == ["#f80", "#000"]


# ─── End-to-end + idempotency ───────────────────────────────────────────


def test_end_to_end_legacy_blob_migrates_cleanly():
    out, notes = migrate(_legacy_blob())

    # All legacy signals gone
    assert is_legacy_config(out) is False
    # All target shapes present
    assert out["general"]["log_level"] == "info"
    assert out["user_interface"]["theme"] == "dark"
    assert out["unmatched_assets"]["ignore_folders"] == ["/mnt/junk"]
    # Plex dict entry split into plex_scope; only ARR names remain in instances.
    assert out["unmatched_assets"]["instances"] == ["radarr", "sonarr"]
    assert out["unmatched_assets"]["plex_scope"][0]["instance"] == "Plex"
    assert out["unmatched_assets"]["plex_scope"][0]["library_names"] == [
        "Movies",
        "TV Shows",
    ]
    assert out["renameinatorr"]["ignore_tags"] == "do-not-touch"
    assert out["poster_cleanarr"]["asset_dirs"] == ["/posters"]
    assert out["poster_cleanarr"]["mode"] == "report"
    assert isinstance(out["border_replacerr"]["holidays"], list)
    assert out["labelarr"]["mappings"][0]["plex_instances"][0]["instance"] == "plex_1"

    # At least one note per rule that fired
    assert len(notes) >= 10
    # At least one warning (for the dropped sections/fields)
    assert any(n.level == "warning" for n in notes)


def test_migrate_is_idempotent():
    once, _ = migrate(_legacy_blob())
    twice, second_notes = migrate(once)
    assert twice == once
    assert second_notes == []


def test_migrate_does_not_mutate_input():
    original = _legacy_blob()
    snapshot = {**original, "main": dict(original["main"])}
    migrate(original)
    assert original["main"] == snapshot["main"]
    assert "main" in original


# ─── poster_cleanarr instances split ────────────────────────────────────


def _cleanarr_presplit():
    """A chub-native config that still mixes ARR names into
    `poster_cleanarr.instances` (the pre-orphan_instances shape)."""
    return {
        "instances": {
            "plex": {"Chodeus": {"url": "x", "api": "y"}},
            "radarr": {"radarr": {}, "radarr4k": {}},
            "sonarr": {"sonarr": {}},
        },
        "poster_cleanarr": {
            "mode": "report",
            "instances": ["Chodeus", "radarr", "radarr4k", "sonarr"],
        },
    }


def test_detection_cleanarr_presplit_instances_triggers():
    assert is_legacy_config(_cleanarr_presplit()) is True


def test_detection_cleanarr_plex_only_instances_is_native():
    cfg = {
        "instances": {"plex": {"Chodeus": {}}},
        "poster_cleanarr": {"mode": "report", "instances": ["Chodeus"]},
    }
    assert is_legacy_config(cfg) is False


def test_detection_cleanarr_with_orphan_instances_is_native():
    cfg = _cleanarr_presplit()
    cfg["poster_cleanarr"]["orphan_instances"] = ["radarr"]
    assert is_legacy_config(cfg) is False


def test_rule_split_cleanarr_instances_moves_arr_to_orphan():
    out, notes = migrate(_cleanarr_presplit())
    sec = out["poster_cleanarr"]
    assert sec["instances"] == ["Chodeus"]
    assert sec["orphan_instances"] == ["radarr", "radarr4k", "sonarr"]
    assert any("split:poster_cleanarr.instances" in n.rule for n in notes)


def test_rule_split_cleanarr_keeps_unknown_names_in_instances():
    cfg = {
        "instances": {"plex": {"Chodeus": {}}, "radarr": {"radarr": {}}},
        "poster_cleanarr": {"instances": ["Chodeus", "radarr", "ghost"]},
    }
    out, _ = migrate(cfg)
    sec = out["poster_cleanarr"]
    assert sec["orphan_instances"] == ["radarr"]
    assert sec["instances"] == ["Chodeus", "ghost"]  # unknown name preserved


def test_rule_split_cleanarr_instances_is_idempotent():
    once, _ = migrate(_cleanarr_presplit())
    twice, second_notes = migrate(once)
    assert twice == once
    assert not any("split:poster_cleanarr.instances" in n.rule for n in second_notes)


# ─── poster_cleanarr instances flatten (legacy plex dict entries) ─────────


def test_detection_cleanarr_plex_dict_entry_triggers():
    assert (
        is_legacy_config(
            {
                "poster_cleanarr": {
                    "instances": [{"plex": {"library_names": ["Movies"]}}]
                }
            }
        )
        is True
    )


def test_rule_flatten_cleanarr_plex_dict_entry():
    out, notes = migrate(
        {"poster_cleanarr": {"instances": [{"plex": {"library_names": ["Movies"]}}]}}
    )
    assert out["poster_cleanarr"]["instances"] == ["plex"]
    assert any(
        n.rule == "flatten:poster_cleanarr.instances" and n.level == "warning"
        for n in notes
    )


def test_rule_flatten_cleanarr_instances_all_strings_is_noop():
    out, notes = migrate({"poster_cleanarr": {"instances": ["plex"]}})
    assert out["poster_cleanarr"]["instances"] == ["plex"]
    assert not any(n.rule == "flatten:poster_cleanarr.instances" for n in notes)


def test_real_config_split_preserves_effective_scope():
    raw = {
        "main": {"theme": "dark"},
        "poster_renamerr": {
            "instances": [
                "Movies",
                "Shows",
                {
                    "Plex": {
                        "library_names": ["Movies", "Anime", "Shows"],
                        "add_posters": True,
                    }
                },
            ]
        },
        "unmatched_assets": {
            "instances": [
                "Movies",
                "Shows",
                {"Plex": {"library_names": ["Movies", "Anime", "Shows", "Music"]}},
            ]
        },
    }
    out, _ = migrate(raw)
    pr = out["poster_renamerr"]
    assert pr["instances"] == ["Movies", "Shows"]
    assert pr["plex_scope"][0] == {
        "instance": "Plex",
        "library_names": ["Movies", "Anime", "Shows"],
        "add_posters": True,
        "match_collections": True,
    }
    ua = out["unmatched_assets"]
    assert ua["plex_scope"][0]["library_names"] == ["Movies", "Anime", "Shows", "Music"]
    from backend.util.config import ChubConfig

    ChubConfig.model_validate(out)


def test_cleanarr_flatten_then_split_real_daps_shape():
    """The real-world DAPS shape: a plain ARR name + a plex dict entry.

    The plex dict must flatten to a name string first, then the ARR name must
    split out into `orphan_instances`, leaving only the Plex name in
    `instances` so it validates against the `List[str]` schema.
    """
    cfg = {
        "instances": {
            "plex": {"plex": {"url": "x", "api": "y"}},
            "radarr": {"radarr-uhd": {}},
        },
        "poster_cleanarr": {
            "dry_run": True,
            "instances": ["radarr-uhd", {"plex": {"library_names": ["Movies"]}}],
        },
    }
    out, _ = migrate(cfg)
    sec = out["poster_cleanarr"]
    assert sec["instances"] == ["plex"]
    assert sec["orphan_instances"] == ["radarr-uhd"]
    assert all(isinstance(i, str) for i in sec["instances"])
    assert is_legacy_config(out) is False  # fully migrated, no second pass needed

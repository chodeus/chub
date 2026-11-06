"""Pins Upgradinatorr's Discord embeds: summary, capped lists, diffs and Discord's limits."""

import pytest

from backend.util.constants import NOTIFICATION_ITEM_CAP, SUMMARY_PART_THRESHOLD
from backend.util.upgradinatorr_notification import (
    _instance_parts,
    QUEUE_LINE_CAP,
    build_upgradinatorr_embeds,
)

FOOTER = "Powered by: CHUB"


def _run(**overrides):
    run = {
        "server_name": "Radarr",
        "data": [],
        "completed": [],
        "pending_grabs": 0,
        "searches_attempted": 5,
        "searches_failed": 0,
        "searches_deferred": 0,
        "tagged_count": 40,
        "untagged_count": 80,
        "total_count": 120,
        "tagged_in_run": 5,
        "instance_type": "radarr",
        "search_mode": "upgrade",
        "budget": 5,
        "granular": False,
    }
    run.update(overrides)
    return run


def _upgrade(n, **overrides):
    entry = {
        "media_id": n,
        "title": f"Movie {n}",
        "year": 2001,
        "download": f"Movie.{n}.2001.1080p.BluRay-GRP",
        "score": 1715,
        "previous_score": 900,
        "quality": "Bluray-1080p",
        "previous_quality": "WEBDL-1080p",
        "custom_formats": ["1080p", "BHDStudio", "DTS-HD MA", "HD Bluray Tier 01"],
        "previous_custom_formats": ["1080p", "AMZN", "DD+"],
        "replaced": True,
    }
    entry.update(overrides)
    return entry


def _stuck(n, message="Not an upgrade for existing movie file."):
    return {
        "media_id": n,
        "title": f"Stuck {n}",
        "year": 1992,
        "grabs": [],
        "queue_imports": [
            {
                "state": "stuck",
                "download": f"Stuck.{n}.1992.1080p-GRP",
                "age_hours": 30.0,
                "messages": [message, "second reason"],
            }
        ],
    }


def _text(parts):
    return "\n".join(
        [part.get("description") or "" for part in parts]
        + [f"{f['name']}\n{f['value']}" for part in parts for f in part["fields"]]
    )


def test_the_summary_states_the_search_the_rotation_and_the_imports():
    data = [
        {"media_id": 1, "grabs": [{"download_id": "a"}, {"download_id": "b"}]},
        {"media_id": 2, "grabs": []},
    ]
    run = _run(
        data=data,
        searches_failed=1,
        completed=[_upgrade(1), _upgrade(2, replaced=False)],
        pending_grabs=3,
    )

    [part] = build_upgradinatorr_embeds({"radarr": run})

    assert part["title"] == "Upgradinatorr: Radarr"
    assert part["description"].split("\n") == [
        "Upgrade search: searched 5 this run, 2 grabbed, 1 failed",
        "Progress: 45 of 120 movies searched, 75 left (15 more runs at 5 a run)",
        "Imported: 2 of 3 grabs from earlier runs (1 upgraded, 1 acquired)",
    ]


def test_season_mode_progress_uses_the_counts_from_before_the_run():
    """Season/album mode can stop mid-parent untagged, so progress uses pre-run counts."""
    run = _run(instance_type="sonarr", granular=True, tagged_in_run=99)

    [part] = build_upgradinatorr_embeds({"sonarr": run})

    assert "Progress: 40 of 120 series done before this run" in part["description"]
    assert "more run" not in part["description"]


def test_a_finished_rotation_estimates_no_more_runs():
    run = _run(tagged_count=118, tagged_in_run=2, searches_attempted=0)

    [part] = build_upgradinatorr_embeds({"radarr": run})

    assert part["description"].split("\n") == [
        "Upgrade search: nothing searched this run",
        "Progress: 120 of 120 movies searched, 0 left",
    ]


def test_an_imports_only_result_has_no_search_or_progress_line():
    """_completed_only results carry no budget: nothing was left to search."""
    run = {
        "server_name": "Radarr",
        "data": [],
        "completed": [_upgrade(1)],
        "pending_grabs": 1,
    }

    [part] = build_upgradinatorr_embeds({"radarr": run})

    assert part["description"] == "Imported: 1 of 1 grab from earlier runs (1 upgraded)"


def test_an_upgrade_is_a_diff_of_the_old_and_new_file():
    [part] = build_upgradinatorr_embeds({"radarr": _run(completed=[_upgrade(1)])})

    [field] = part["fields"]
    assert field["name"] == "Movie 1 (2001) — upgraded"
    assert field["value"] == (
        "Release: Movie.1.2001.1080p.BluRay-GRP\n"
        "```diff\n"
        "- WEBDL-1080p\n"
        "- CF: 1080p, AMZN, DD+\n"
        "- Score: 900\n"
        "+ Bluray-1080p\n"
        "+ CF: 1080p, BHDStudio, DTS-HD MA, HD Bluray\n"
        "+     Tier 01\n"
        "+ Score: 1715\n"
        "```"
    )


def test_a_zero_score_is_shown_and_an_empty_format_list_says_none():
    entry = _upgrade(1, score=0, custom_formats=[], replaced=False)

    [part] = build_upgradinatorr_embeds({"radarr": _run(completed=[entry])})

    assert "+ CF: none\n+ Score: 0\n```" in part["fields"][0]["value"]


def test_markdown_in_titles_and_release_names_is_escaped():
    entry = _upgrade(1, download="Some_Movie_2006*Cut*")
    stuck = _stuck(1, message="Has `ticks` and |pipes|")
    stuck["title"] = "Under_score"

    parts = build_upgradinatorr_embeds(
        {"radarr": _run(data=[stuck], completed=[entry])}
    )
    text = _text(parts)

    assert r"Release: Some\_Movie\_2006\*Cut\*" in text
    assert r"• Under\_score (1992): Has \`ticks\` and \|pipes\|" in text


def test_a_backtick_cannot_close_the_diff_fence():
    entry = _upgrade(1, custom_formats=["weird```name"])

    [part] = build_upgradinatorr_embeds({"radarr": _run(completed=[entry])})

    assert part["fields"][0]["value"].count("```") == 2


def test_stuck_items_show_the_first_reason_and_cap_the_list():
    data = [_stuck(n) for n in range(QUEUE_LINE_CAP + 2)]

    parts = build_upgradinatorr_embeds({"radarr": _run(data=data)})
    text = _text(parts)

    assert f"Import stuck ({QUEUE_LINE_CAP + 2})" in text
    assert "• Stuck 0 (1992): Not an upgrade for existing movie file." in text
    assert f"Stuck {QUEUE_LINE_CAP - 1} (1992)" in text
    assert f"Stuck {QUEUE_LINE_CAP} (1992)" not in text
    assert "…and 2 more — see the server log" in text
    assert "second reason" not in text
    assert "Stuck.0.1992" not in text


def test_a_waiting_item_with_several_downloads_names_the_oldest():
    item = {
        "media_id": 1,
        "title": "Show",
        "year": None,
        "grabs": [],
        "queue_imports": [
            {"state": "pending", "age_hours": 3.2, "messages": []},
            {"state": "pending", "age_hours": 41.6, "messages": []},
        ],
    }

    [part] = build_upgradinatorr_embeds({"sonarr": _run(data=[item])})

    assert part["fields"][0] == {
        "name": "Awaiting import (1)",
        "value": "• Show: 2 downloads, oldest waiting 42h",
    }


def test_imports_past_the_cap_point_at_the_server_log():
    completed = [_upgrade(n) for n in range(NOTIFICATION_ITEM_CAP + 3)]

    text = _text(build_upgradinatorr_embeds({"radarr": _run(completed=completed)}))

    assert f"Movie {NOTIFICATION_ITEM_CAP - 1} (2001) — upgraded" in text
    assert f"Movie {NOTIFICATION_ITEM_CAP} (2001)" not in text
    assert "…and 3 more upgrades — see the server log" in text


@pytest.mark.parametrize("diffs", [True, False])
def test_every_part_fits_discord_limits_at_the_caps(diffs):
    """At the caps' worst case, every part stays inside Discord's limits."""
    long_name = "_" * 400
    formats = [f"Custom Format Number {n}" for n in range(30)]
    # Every field maximised at once, first so the per-section cap keeps it.
    worst = _upgrade(
        0,
        title=long_name,
        download=long_name,
        quality="Q" * 500,
        previous_quality="P" * 500,
        custom_formats=formats,
        previous_custom_formats=formats,
        score=-123456789,
        previous_score=-123456789,
    )
    completed = [worst] + [
        _upgrade(n, title=long_name, download=long_name, custom_formats=formats)
        for n in range(NOTIFICATION_ITEM_CAP + 5)
    ] + [
        _upgrade(n, replaced=False, quality="Q" * 500, custom_formats=formats)
        for n in range(NOTIFICATION_ITEM_CAP + 5)
    ]
    data = [_stuck(n, message="x" * 2000) for n in range(QUEUE_LINE_CAP + 5)]
    for item in data:
        item["title"] = long_name
    not_imported = [
        {"title": long_name, "year": 2001, "download": long_name, "reason": "x" * 2000}
        for _ in range(QUEUE_LINE_CAP + 5)
    ]
    run = _run(
        server_name="S" * 400,
        data=data,
        completed=completed,
        not_imported=not_imported,
        inflight_finished={"label": long_name, "state": "failed"},
    )

    # Called directly: a run this big reaches build_upgradinatorr_embeds as counts only.
    parts = _instance_parts("radarr", run, diffs)

    assert ("```diff" in _text(parts)) is diffs
    assert len(parts) > 1
    for index, part in enumerate(parts, 1):
        assert part["part"] == f" (part {index} of {len(parts)})"
        title = part["title"] + part["part"]
        assert len(title) <= 256
        assert len(part["fields"]) <= 25
        assert len(part.get("description") or "") <= 4096
        total = len(title) + len(part.get("description") or "") + len(FOOTER)
        for field in part["fields"]:
            assert 0 < len(field["name"]) <= 256
            assert 0 < len(field["value"]) <= 1024
            total += len(field["name"]) + len(field["value"])
        assert total <= 6000


def test_many_small_fields_split_at_discords_field_count():
    completed = [
        {"media_id": n, "title": f"M{n}", "replaced": False, "score": n}
        for n in range(NOTIFICATION_ITEM_CAP + 10)
    ]

    parts = build_upgradinatorr_embeds({"radarr": _run(completed=completed)})

    assert [len(part["fields"]) for part in parts] == [25, 25, 1]
    assert parts[0]["description"] and parts[1]["description"] is None


def test_a_run_past_the_message_budget_counts_its_imports_instead():
    completed = [_upgrade(n, download="_" * 200) for n in range(NOTIFICATION_ITEM_CAP)]
    output = {
        name: _run(server_name=name, completed=completed, pending_grabs=len(completed))
        for name in ("Radarr", "Radarr 4K")
    }
    full = [p for name, run in output.items() for p in _instance_parts(name, run, True)]
    assert len(full) > SUMMARY_PART_THRESHOLD

    parts = build_upgradinatorr_embeds(output)

    assert [part["title"] for part in parts] == [
        "Upgradinatorr: Radarr",
        "Upgradinatorr: Radarr 4K",
    ]
    for part in parts:
        assert "Imported: 50 of 50 grabs from earlier runs (50 upgraded)" in (
            part["description"]
        )
        assert part["fields"] == [
            {
                "name": "Imports (50)",
                "value": "Too many to show one by one: "
                "the server log lists each import.",
            }
        ]


def test_one_embed_set_per_instance():
    output = {"radarr": _run(), "radarr4k": _run(server_name="Radarr 4K")}

    titles = [part["title"] for part in build_upgradinatorr_embeds(output)]

    assert titles == ["Upgradinatorr: Radarr", "Upgradinatorr: Radarr 4K"]


def test_an_album_label_uses_the_release_year_and_primary_type():
    from backend.util.constants import report_item_label

    album = {"title": "On My Way", "type": "Single", "year": 2015}
    assert report_item_label({"title": "Axwell", "year": 1977, "album": album}) == (
        "Axwell - On My Way (2015) [Single]"
    )
    assert report_item_label({"title": "A", "album": {"title": "B"}}) == "A - B"
    assert report_item_label({"title": "Alien", "year": 1979}) == "Alien (1979)"
    assert report_item_label({}) == "Unknown"


def _missed(n, reason="Duplicate NZB"):
    return {
        "media_id": n,
        "title": f"Gone {n}",
        "year": 2020,
        "download": f"Gone.{n}.2020_1080p-GRP",
        "reason": reason,
    }


def test_grabs_that_did_not_import_are_listed_and_counted():
    run = _run(completed=[_upgrade(1)], not_imported=[_missed(2)], pending_grabs=3)

    parts = build_upgradinatorr_embeds({"radarr": run})

    assert parts[0]["description"].split("\n")[-1] == (
        "Imported: 1 of 3 grabs from earlier runs (1 upgraded); 1 didn't import"
    )
    assert parts[0]["fields"][0] == {
        "name": "Didn't import (1)",
        "value": r"• Gone 2 (2020): Gone.2.2020\_1080p-GRP — Duplicate NZB",
    }
    assert parts[0]["fields"][1]["name"] == "Movie 1 (2001) — upgraded"


def test_the_did_not_import_list_is_capped():
    rows = [_missed(n) for n in range(QUEUE_LINE_CAP + 3)]

    text = _text(build_upgradinatorr_embeds({"radarr": _run(not_imported=rows)}))

    assert f"Didn't import ({QUEUE_LINE_CAP + 3})" in text
    assert f"Gone {QUEUE_LINE_CAP - 1} (2020)" in text
    assert f"Gone {QUEUE_LINE_CAP} (2020)" not in text
    assert "…and 3 more — see the server log" in text


def test_the_embed_colour_follows_the_run_outcome():
    from backend.util.upgradinatorr_notification import GREEN, RED

    grabbed = [{"media_id": 1, "grabs": [{"download_id": "a"}]}]
    cases = {
        "failed": _run(searches_failed=1, data=grabbed),
        "grabbed": _run(data=grabbed),
        "imported": _run(completed=[_upgrade(1)]),
        "quiet": _run(),
    }

    colours = {
        name: [part.get("color") for part in build_upgradinatorr_embeds({name: run})]
        for name, run in cases.items()
    }

    assert colours == {
        "failed": [RED],
        "grabbed": [GREEN],
        "imported": [GREEN],
        "quiet": [None],
    }


def test_every_part_of_a_split_embed_carries_the_colour():
    from backend.util.upgradinatorr_notification import GREEN

    completed = [_upgrade(n) for n in range(30)]

    parts = build_upgradinatorr_embeds({"radarr": _run(completed=completed)})

    assert len(parts) > 1
    assert {part.get("color") for part in parts} == {GREEN}

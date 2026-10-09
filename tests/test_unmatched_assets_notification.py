"""Unmatched Assets notifications carry per-type counts and name their source."""

from types import SimpleNamespace

from backend.modules.unmatched_assets import UnmatchedAssets
from backend.util.notification_formatting import format_for_discord

SUMMARY = [
    ["Type", "Total", "Unmatched", "Percent Complete"],
    ["Movies", 10, 2, "80.00%"],
    ["Series", 4, 0, "100.00%"],
    ["Grand Total", 14, 2, "85.71%"],
]


def _fields(output):
    module = SimpleNamespace(module_name="unmatched_assets")
    parts, ok = format_for_discord(module, output)
    assert ok is True
    # split_fields code-fences every value; compare the text inside
    return [
        {**field, "value": field["value"].strip("`")}
        for chunk in parts.values()
        for field in chunk
    ]


def test_sends_the_counts_and_names_poster_renamerr_as_the_source():
    last_run = "2026-10-09T10:00:00.123456+00:00"
    fields = _fields({"summary": SUMMARY, "last_match": last_run})

    text = "\n".join(f"{f['name']}: {f['value']}" for f in fields)
    assert "Movies: 2 of 10 unmatched (80.00% complete)" in text
    assert "Grand Total: 2 of 14 unmatched (85.71% complete)" in text
    assert "Based on: Poster Renamerr's last match (2026-10-09 " in text
    assert "T10:00" not in text and ".123456" not in text


def test_an_unparseable_time_is_shown_as_is():
    fields = _fields({"summary": SUMMARY, "last_match": "yesterday"})

    based_on = {"name": "Based on", "value": "Poster Renamerr's last match (yesterday)"}
    assert based_on in fields


def test_an_empty_summary_still_says_so():
    fields = _fields({"summary": [SUMMARY[0]], "last_match": None})

    assert fields == [{"name": "Summary", "value": "No media to check yet."}]


def test_build_output_carries_poster_renamerrs_last_run():
    module = UnmatchedAssets.__new__(UnmatchedAssets)
    stats = {"unmatched": {}, "summary": {
        key: {"total": 0, "unmatched": 0, "percent_complete": 0.0}
        for key in ("movies", "series", "seasons", "collections", "grand_total")
    }}
    module.get_stats = lambda db: stats
    asked = []
    db = SimpleNamespace(
        run_state=SimpleNamespace(
            get_run_state=lambda name: asked.append(name)
            or {"last_run": "2026-10-09T10:00:00"}
        )
    )

    output = module.build_output(db)

    assert output["last_match"] == "2026-10-09T10:00:00"
    assert asked == ["poster_renamerr"]

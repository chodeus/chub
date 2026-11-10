"""Upgradinatorr's report text: the run log's summary lines and its Discord/Notifiarr embeds."""

import math
import textwrap
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.util.constants import (
    NOTIFICATION_ITEM_CAP,
    QUEUE_REPORT_SECTIONS,
    SUMMARY_PART_THRESHOLD,
    counted,
    plural,
    report_item_label,
    import_report_sections,
)

QUEUE_LINE_CAP = 10
REASON_CHARS = 200
RELEASE_CHARS = 200
QUALITY_CHARS = 60
# Columns a phone shows in a code block before Discord wraps the line itself.
DIFF_WIDTH = 46
CF_LINE_CAP = 4

# Discord's title cap is 256; the rest is room for the " (part i of n)" suffix.
TITLE_CHARS = 200
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
DESCRIPTION_LIMIT = 4096
EMBED_FIELD_LIMIT = 25
# Discord rejects an embed over 6000 characters; the rest covers footer and part suffix.
EMBED_CHAR_BUDGET = 5500
BLANK = "​"

RED = 0xE74C3C
GREEN = 0x2ECC71

# Brackets too: an escaped [ can't open a masked link.
_MARKDOWN = str.maketrans({char: f"\\{char}" for char in "\\*_~`|[]"})


def _md(text: Any) -> str:
    return str(text).translate(_MARKDOWN)


def _code(text: Any) -> str:
    """Text safe inside a code block, where a backtick would close the fence."""
    return str(text).replace("`", "'")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def searched_text(run: Dict[str, Any]) -> str:
    """``1 series searched (4 seasons)``: parents searched, then their season/album searches."""
    kind = run.get("instance_type")
    text = f"{counted(run.get('items_searched') or 0, kind)} searched"
    children = run.get("child_searches") or 0
    return f"{text} ({counted(children, kind, 'child')})" if children else text


def _search_line(run: Dict[str, Any]) -> Optional[str]:
    # No budget means process_instance found nothing to search and only reports imports.
    if "budget" not in run:
        return None
    mode = str(run.get("search_mode") or "upgrade").capitalize()
    if not run.get("searches_attempted"):
        return f"{mode} search: nothing searched this run"
    grabbed = sum(len(item.get("grabs") or []) for item in run.get("data") or [])
    parts = [searched_text(run), f"{grabbed} grabbed"]
    if run.get("searches_failed"):
        parts.append(f"{plural(run['searches_failed'], 'search', 'searches')} failed")
    if run.get("searches_deferred"):
        staged = plural(run["searches_deferred"], "search", "searches")
        parts.append(f"{staged} staged for the next run")
    return f"{mode} search: " + ", ".join(parts)


def _progress_line(run: Dict[str, Any]) -> Optional[str]:
    total = run.get("total_count") or 0
    if "budget" not in run or not total:
        return None
    of_total = counted(total, run.get("instance_type"))
    tagged = run.get("tagged_count") or 0
    if run.get("granular"):
        # Season/album mode can stop mid-parent untagged, so this run's tag count is unknown.
        return f"Progress: {tagged} of {of_total} done before this run"
    tagged = min(tagged + (run.get("tagged_in_run") or 0), total)
    left = total - tagged
    line = f"Progress: {tagged} of {of_total} searched, {left} left"
    budget = run.get("budget") or 0
    if left and budget > 0:
        runs = plural(math.ceil(left / budget), "more run")
        line += f" ({runs} at {budget} a run)"
    return line


def _all_tagged(tag: str) -> str:
    return f'everything is tagged "{tag}" and Auto reset processed tag is off'


def _rotation_line(run: Dict[str, Any], escape: Callable[[Any], str]) -> Optional[str]:
    if not run.get("rotation_done"):
        return None
    return (
        f"Rotation finished: {_all_tagged(escape(run.get('tag_name')))}, "
        "so nothing is searched until the tag is removed"
    )


def nothing_to_search_text(
    name: str,
    kind: Any,
    search_mode: str,
    wanted: Optional[int],
    total: int,
    untagged: int,
    tag: str,
) -> str:
    """The run log's reason a profile with no candidates searches nothing."""
    if not total:
        if wanted is not None:
            return f"Nothing to search on {name}: its {search_mode} list is empty."
        return f"Nothing to search on {name}: {counted(0, kind)} found."
    if not untagged:
        return (
            f"Nothing to search on {name} ({counted(total, kind)}): {_all_tagged(tag)}. "
            "Remove the tag or turn on Auto reset to start a new rotation."
        )
    return (
        f"Nothing to search on {name}: {counted(untagged, kind)} untagged, all skipped "
        "by the filters (debug logging names each reason)."
    )


def selection_text(
    kind: Any,
    search_mode: str,
    wanted: Optional[int],
    total: int,
    candidates: int,
    count: int,
    granular: bool,
) -> str:
    """The run log's line on what the wanted list held and what this run searches."""
    if granular:
        line = (
            f"{counted(candidates, kind)} left to search; this run searches up to "
            f"{counted(count, kind, 'child')}."
        )
    else:
        line = (
            f"Selected {candidates} of {counted(total, kind)} to search "
            f"(Count: {counted(count, kind)} a run)."
        )
    if wanted is None:
        return line
    found = counted(wanted, kind, "wanted")
    if kind in ("sonarr", "lidarr"):
        found += f" across {counted(total, kind)}"
    return f"Wanted ({search_mode}): {found}. {line}"


def _limit_line(run: Dict[str, Any]) -> Optional[str]:
    cap = run.get("max_grabs_hit")
    if not cap:
        return None
    return (
        f"Max Items Grabbed Per Run reached: {counted(cap, run.get('instance_type'))} "
        "grabbed something, the rest is searched next run"
    )


def _inflight_line(run: Dict[str, Any], escape: Callable[[Any], str]) -> Optional[str]:
    if run.get("inflight_running"):
        return (
            f"Waiting on the last run's search of {escape(run['inflight_running'])}: "
            "nothing new is searched until it finishes"
        )
    finished = run.get("inflight_finished") or {}
    if not finished:
        return None
    label = escape(finished.get("label"))
    if finished.get("state") == "failed":
        return f"The last run's search of {label} failed"
    return f"Finished the last run's search of {label}"


def held_line(holds: Dict[str, Any], instance_type: Any) -> Optional[str]:
    """``Held back: 2 movies released in the last 7 days``, or None when nothing was held."""
    # Lidarr artists carry no date, so its albums are what gets held.
    unit = "child" if instance_type == "lidarr" else "parent"
    parts = []
    if holds.get("too_new"):
        too_new = counted(holds["too_new"], instance_type, unit)
        parts.append(f"{too_new} released in the last {plural(holds.get('days') or 0, 'day')}")
    if holds.get("no_date"):
        parts.append(f"{counted(holds['no_date'], instance_type, unit)} with no release date")
    return f"Held back: {', '.join(parts)}" if parts else None


def _imported_line(run: Dict[str, Any]) -> Optional[str]:
    pending = run.get("pending_grabs") or 0
    if not pending:
        return None
    completed = run.get("completed") or []
    line = f"Imported: {len(completed)} of {plural(pending, 'grab')} from earlier runs"
    kinds = [
        f"{len(rows)} {tag.lower()}"
        for tag, _noun, rows in import_report_sections(completed)
    ]
    if kinds:
        line += f" ({', '.join(kinds)})"
    missed = len(run.get("not_imported") or [])
    return f"{line}; {missed} didn't import" if missed else line


def _queue_rows(
    data: List[Dict[str, Any]], state: str
) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    rows = []
    for item in data:
        entries = [e for e in item.get("queue_imports") or [] if e.get("state") == state]
        if entries:
            rows.append((item, entries))
    return rows


def _queue_line(
    item: Dict[str, Any], entries: List[Dict[str, Any]], state: str
) -> str:
    head = f"• {_md(report_item_label(item))}"
    if state == "stuck":
        reasons = [m for e in entries for m in e.get("messages") or [] if m]
        return f"{head}: {_md(_clip(str(reasons[0]), REASON_CHARS))}" if reasons else head
    ages = [e["age_hours"] for e in entries if e.get("age_hours") is not None]
    waiting = f"waiting {max(ages):.0f}h" if ages else "waiting"
    if len(entries) > 1:
        return f"{head}: {len(entries)} downloads, oldest {waiting}"
    return f"{head}: {waiting}"


def _line_fields(name: str, lines: List[str]) -> List[Dict[str, str]]:
    """Lines packed into as few fields as fit, the name on the first only."""
    chunks: List[List[str]] = [[]]
    for line in lines:
        line = _clip(line, FIELD_VALUE_LIMIT)
        if chunks[-1] and len("\n".join(chunks[-1] + [line])) > FIELD_VALUE_LIMIT:
            chunks.append([])
        chunks[-1].append(line)
    return [
        {"name": _clip(name, FIELD_NAME_LIMIT) if i == 0 else BLANK, "value": "\n".join(c)}
        for i, c in enumerate(chunks)
    ]


def _queue_fields(data: List[Dict[str, Any]], kind: Any) -> List[Dict[str, str]]:
    fields: List[Dict[str, str]] = []
    for state, tag, _note, _level in QUEUE_REPORT_SECTIONS:
        rows = _queue_rows(data, state)
        if not rows:
            continue
        lines = [_queue_line(item, entries, state) for item, entries in rows[:QUEUE_LINE_CAP]]
        if len(rows) > QUEUE_LINE_CAP:
            lines.append(f"…and {len(rows) - QUEUE_LINE_CAP} more — see the server log")
        fields.extend(_line_fields(f"{tag.capitalize()} ({counted(len(rows), kind)})", lines))
    return fields


def _not_imported_fields(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not rows:
        return []
    lines = [
        f"• {_md(report_item_label(row))}: "
        f"{_md(_clip(str(row.get('download') or ''), RELEASE_CHARS))} — "
        f"{_md(_clip(str(row.get('reason') or ''), REASON_CHARS))}"
        for row in rows[:QUEUE_LINE_CAP]
    ]
    if len(rows) > QUEUE_LINE_CAP:
        lines.append(f"…and {len(rows) - QUEUE_LINE_CAP} more — see the server log")
    return _line_fields(f"Didn't import ({plural(len(rows), 'grab')})", lines)


def _wrap_formats(formats: List[str]) -> List[str]:
    text = ", ".join(_code(name) for name in formats) or "none"
    rows = textwrap.wrap(
        text,
        width=DIFF_WIDTH - 2,
        initial_indent="CF: ",
        subsequent_indent="    ",
        break_on_hyphens=False,
    )
    if len(rows) > CF_LINE_CAP:
        rows = rows[:CF_LINE_CAP]
        rows[-1] += " …"
    return rows


def _diff_side(
    sign: str, quality: Any, formats: Optional[List[str]], score: Any
) -> List[str]:
    lines = []
    if quality:
        lines.append(f"{sign} {_clip(_code(quality), QUALITY_CHARS)}")
    if formats is not None:
        lines.extend(f"{sign} {row}" for row in _wrap_formats(formats))
    # None is unknown; 0 is a real score.
    if score is not None:
        lines.append(f"{sign} Score: {score}")
    return lines


def _import_value(entry: Dict[str, Any]) -> str:
    lines = []
    if entry.get("download"):
        lines.append(f"Release: {_md(_clip(str(entry['download']), RELEASE_CHARS))}")
    diff: List[str] = []
    if entry.get("replaced"):
        diff += _diff_side(
            "-",
            entry.get("previous_quality"),
            entry.get("previous_custom_formats"),
            entry.get("previous_score"),
        )
    diff += _diff_side(
        "+", entry.get("quality"), entry.get("custom_formats"), entry.get("score")
    )
    if diff:
        lines.append("```diff\n" + "\n".join(diff) + "\n```")
    return "\n".join(lines) or BLANK


def _import_fields(completed: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    fields: List[Dict[str, str]] = []
    for tag, noun, rows in import_report_sections(completed):
        for entry in rows[:NOTIFICATION_ITEM_CAP]:
            name = f"{_md(report_item_label(entry))} — {tag.lower()}"
            fields.append(
                {"name": _clip(name, FIELD_NAME_LIMIT), "value": _import_value(entry)}
            )
        extra = len(rows) - NOTIFICATION_ITEM_CAP
        if extra > 0:
            more = plural(extra, f"more {noun}")
            fields.append({"name": BLANK, "value": f"…and {more} — see the server log"})
    return fields


def _outcome_color(run: Dict[str, Any]) -> Optional[int]:
    """Red when a search failed, green when something was grabbed or imported, else None."""
    # None leaves the Discord destination's own colour in charge.
    if run.get("searches_failed"):
        return RED
    grabbed = any(item.get("grabs") for item in run.get("data") or [])
    return GREEN if grabbed or run.get("completed") else None


def _embeds(
    title: str, description: Optional[str], fields: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Fields split across embeds by Discord's field-count and size limits."""
    parts = [{"embed": True, "title": title, "description": description, "fields": []}]
    size = len(title) + len(description or "")
    for field in fields:
        cost = len(field["name"]) + len(field["value"])
        current = parts[-1]["fields"]
        if current and (
            len(current) >= EMBED_FIELD_LIMIT or size + cost > EMBED_CHAR_BUDGET
        ):
            parts.append({"embed": True, "title": title, "description": None, "fields": []})
            size = len(title)
        parts[-1]["fields"].append(field)
        size += cost
    if len(parts) > 1:
        for index, part in enumerate(parts, 1):
            part["part"] = f" (part {index} of {len(parts)})"
    return parts


def _import_count_field(completed: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not completed:
        return []
    return [
        {
            "name": f"Imports ({len(completed)})",
            "value": "Too many to show one by one: the server log lists each import.",
        }
    ]


def summary_lines(run: Dict[str, Any], escape: Callable[[Any], str] = str) -> List[str]:
    """The run summary the log and the embed both print; ``escape`` guards names for Discord."""
    lines = (
        _search_line(run),
        _inflight_line(run, escape),
        _progress_line(run),
        _rotation_line(run, escape),
        _limit_line(run),
        held_line(run.get("release_holds") or {}, run.get("instance_type")),
        _imported_line(run),
    )
    return [line for line in lines if line]


def _instance_parts(
    name: str, run: Dict[str, Any], diffs: bool
) -> List[Dict[str, Any]]:
    """One instance's embeds; without ``diffs`` its imports are only counted."""
    title = _clip(f"Upgradinatorr: {run.get('server_name') or name}", TITLE_CHARS)
    lines = summary_lines(run, _md)
    completed = run.get("completed") or []
    fields = (
        _queue_fields(run.get("data") or [], run.get("instance_type"))
        + _not_imported_fields(run.get("not_imported") or [])
        + (_import_fields(completed) if diffs else _import_count_field(completed))
    )
    description = _clip("\n".join(lines), DESCRIPTION_LIMIT) or None
    if not description and not fields:
        description = "Nothing to report this run."
    color = _outcome_color(run)
    parts = _embeds(title, description, fields)
    if color is not None:
        for part in parts:
            part["color"] = color
    return parts


def build_upgradinatorr_embeds(output: Any) -> List[Dict[str, Any]]:
    """One embed set per instance: summary, queue lists, then a diff per import."""
    runs = [(n, run) for n, run in (output or {}).items() if isinstance(run, dict)]
    parts = [part for name, run in runs for part in _instance_parts(name, run, True)]
    if len(parts) <= SUMMARY_PART_THRESHOLD:
        return parts
    # Past the message budget every other module collapses at, the diffs become counts.
    return [part for name, run in runs for part in _instance_parts(name, run, False)]

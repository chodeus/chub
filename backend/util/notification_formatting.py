import os
from typing import Any, Dict, List, Tuple

from backend.util.constants import QUEUE_REPORT_SECTIONS, queue_report_tally

# When a run would fan out into more than this many Discord messages (embeds),
# collapse the per-item detail into a single summary embed. A first-time bulk
# poster apply of thousands of items would otherwise hammer the webhook and trip
# Discord's rate limiter; normal runs (a handful of items → 1–2 parts) are
# returned unchanged.
SUMMARY_PART_THRESHOLD = 10


def _collapse_large_notification(
    parts: Dict[int, List[Dict[str, Any]]],
    fields: List[Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    """Replace a many-part embed set with a single summary embed once it exceeds
    ``SUMMARY_PART_THRESHOLD`` messages. Each ``fields`` entry with a non-empty
    ``name`` is one titled item, so that count is the run size. Returns ``parts``
    unchanged for normal-sized runs.
    """
    if len(parts) <= SUMMARY_PART_THRESHOLD:
        return parts
    entry_count = sum(1 for f in fields if f.get("name"))
    summary = [
        {
            "name": f"{entry_count} items processed",
            "value": (
                f"```This run affected {entry_count} items across {len(parts)} "
                "Discord messages. Per-item detail was collapsed into this "
                "summary to stay within Discord's rate limits.```"
            ),
        }
    ]
    return {1: summary}


def format_for_discord(
    config: Any, output: Any
) -> Tuple[Dict[int, List[Dict[str, Any]]], bool]:
    """Format notification output for Discord embeds and chunking.

    Args:
        config: Module config object (must have 'module_name').
        output: Output from the module to be formatted.

    Returns:
        Tuple of (embed field dict, success bool).
    """
    DISCORD_FIELD_CHAR_LIMIT = 1000
    DISCORD_EMBED_CHAR_LIMIT = 5000
    DISCORD_FIELD_COUNT_LIMIT = 25

    def chunk_code_fields(
        name: str, text: str, inline: bool = False
    ) -> List[Dict[str, Any]]:
        """Chunk a string into Discord embed fields by char limit.

        Args:
          name: Name of the field (used for the first chunk).
          text: The code/text to chunk.
          inline: Whether this field should be inline.

        Returns:
          List of Discord embed field dicts.
        """
        fields: List[Dict[str, Any]] = []
        lines = text.split("\n")
        buffer = ""
        first = True
        for line in lines:
            candidate = buffer + line + "\n"
            if len(candidate) > DISCORD_FIELD_CHAR_LIMIT:
                field = {
                    "name": name if first else "",
                    "value": f"```{buffer.rstrip()}```",
                }
                if inline:
                    field["inline"] = True
                fields.append(field)
                buffer = line + "\n"
                first = False
            else:
                buffer = candidate
        if buffer:
            field = {"name": name if first else "", "value": f"```{buffer.rstrip()}```"}
            if inline:
                field["inline"] = True
            fields.append(field)
        return fields

    def split_fields(fields: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
        """Split embed fields into multiple Discord embeds by char and field limits.

        Args:
          fields: List of Discord embed field dicts.

        Returns:
          Dict mapping embed index to list of fields for that embed.
        """
        expanded: List[Dict[str, Any]] = []
        for f in fields:
            name = f.get("name", "")
            inline = f.get("inline", False)
            val = f.get("value", "")
            if val == "":
                chunk = {"name": name, "value": ""}
                if inline:
                    chunk["inline"] = True
                expanded.append(chunk)
                continue

            content = (
                val[3:-3] if val.startswith("```") and val.endswith("```") else val
            )
            # Hard-split any single line longer than the field budget (leave room
            # for the ``` fence + newline) so one long unbroken line can't produce
            # a chunk over Discord's 1024 value limit.
            max_line = DISCORD_FIELD_CHAR_LIMIT - 10
            lines = []
            for ln in content.split("\n"):
                if len(ln) > max_line:
                    lines.extend(
                        ln[i : i + max_line] for i in range(0, len(ln), max_line)
                    )
                else:
                    lines.append(ln)
            buffer = ""
            first = True
            for line in lines:
                candidate = buffer + line + "\n"
                if len(candidate) > DISCORD_FIELD_CHAR_LIMIT:
                    chunk = {
                        "name": name if first else "",
                        "value": f"```{buffer.strip()}```",
                    }
                    if inline:
                        chunk["inline"] = True
                    expanded.append(chunk)
                    buffer = line + "\n"
                    first = False
                else:
                    buffer = candidate
            if buffer:
                chunk = {
                    "name": name if first else "",
                    "value": f"```{buffer.strip()}```",
                }
                if inline:
                    chunk["inline"] = True
                expanded.append(chunk)

        result: Dict[int, List[Dict[str, Any]]] = {}
        batch: List[Dict[str, Any]] = []
        size_acc = 0
        idx = 1
        limit = DISCORD_EMBED_CHAR_LIMIT + 500
        for f in expanded:
            est = len(f.get("name", "")) + len(f.get("value", "")) + 30
            if len(batch) >= DISCORD_FIELD_COUNT_LIMIT or size_acc + est > limit:
                result[idx] = batch
                idx += 1
                batch = []
                size_acc = 0
            batch.append(f)
            size_acc += est
        if batch:
            result[idx] = batch
        return result

    def chunk_flat_content(
        header: str, content: str, footer: str = ""
    ) -> List[Dict[str, Any]]:
        """Chunk plain content into Discord message blocks under 1900 chars.

        Args:
          header: Header to prepend to the first chunk.
          content: The content to chunk.
          footer: Footer to append to the last chunk.

        Returns:
          List of Discord message dicts (with 'content' key).
        """
        CHUNK_LIMIT = 1900
        lines = content.split("\n")
        results = []
        buffer_lines: List[str] = []
        first_chunk = True

        def flush_chunk(buf_lines: List[str], is_last: bool) -> None:
            chunk_text = "\n".join(buf_lines)
            parts: List[str] = []
            if first_chunk and header:
                parts.append(header)
            parts.append(f"```{chunk_text}```")
            if is_last and footer:
                parts.append(footer)
            results.append({"content": "\n".join(parts)})

        for line in lines:
            buffer_lines.append(line)
            total_len = sum(len(line) for line in buffer_lines) + len(buffer_lines) - 1
            if total_len > CHUNK_LIMIT:
                overflow_line = buffer_lines.pop()
                flush_chunk(buffer_lines, is_last=False)
                first_chunk = False
                buffer_lines = [overflow_line]
        if buffer_lines:
            flush_chunk(buffer_lines, is_last=True)
        return results

    def fmt_poster_renamerr(o: Any) -> List[Dict[str, Any]]:
        """Format poster_renamerr output for Discord embeds.

        One grouped block per category — a field per title fanned a bulk rename
        out into hundreds of embed fields.
        """
        from collections import defaultdict

        def lines_for(assets: Any) -> List[str]:
            grouped: Dict[Tuple[Any, Any], List[str]] = defaultdict(list)
            order: List[Tuple[Any, Any]] = []
            for asset in assets or []:
                key = (asset.get("title"), asset.get("year"))
                if key not in grouped:
                    order.append(key)
                grouped[key].extend(
                    asset.get("discord_messages") or asset.get("messages") or []
                )
            out: List[str] = []
            for title, year in order:
                msgs = grouped[(title, year)]
                if not msgs:
                    continue
                out.append(f"{title} ({year})" if year else str(title or ""))
                out.extend(f"    {m}" for m in msgs)
            return out

        fields: List[Dict[str, Any]] = []
        for label, key in (
            ("Collections", "collection"),
            ("Movies", "movie"),
            ("Shows", "show"),
            ("Artists", "artist"),
            ("Albums", "album"),
        ):
            lines = lines_for(o.get(key, []))
            if lines:
                fields.extend(chunk_code_fields(label, "\n".join(lines)))

        if not fields:
            # empty_text lets the caller override the heartbeat line (the plex
            # upload path sends "No posters were uploaded..." instead).
            fields = [
                {"name": o.get("empty_text") or "No files were renamed.", "value": ""}
            ]
        return fields

    def fmt_renameinatorr(o: Any) -> List[Dict[str, Any]]:
        """Format renameinatorr output for Discord embeds.

        Renames are what the run changed, so they stay listed — grouped into
        chunked blocks rather than one embed field per title.
        """
        grouped: Dict[str, List[str]] = {}
        for inst in o.values():
            for item in inst.get("data", []):
                title = item.get("title", "Unknown")
                year = item.get("year")
                name = f"{title}{f' ({year})' if year else ''}"
                lst = grouped.setdefault(name, [])
                if np := item.get("new_path_name"):
                    lst.append("Folder:")
                    lst.append(
                        f"{item.get('path_name', '').lstrip('/')} -> {np.lstrip('/')}"
                    )
                for old, new in item.get("file_info", {}).items():
                    lst.append(old.lstrip("/"))
                    lst.append(new.lstrip("/"))
        lines: List[str] = []
        for name, entries in grouped.items():
            if not entries:
                continue
            lines.append(name)
            lines.extend(f"    {entry}" for entry in entries)
        if not lines:
            return []
        return chunk_code_fields("Renamed", "\n".join(lines))

    def fmt_health_checkarr(o: Any) -> List[Dict[str, Any]]:
        """Format health_checkarr output for Discord embeds.

        Args:
          o: Output data for health_checkarr.

        Returns:
          List of Discord embed field dicts.
        """
        fields: List[Dict[str, Any]] = []
        grouped: Dict[str, List[str]] = {}
        for item in o:
            title = item.get("title", "Untitled")
            year = f" ({item.get('year')})" if item.get("year") else ""
            instance_type = item.get("instance_type", "")
            db_id = (
                item.get("tvdb_id")
                if instance_type == "sonarr"
                else item.get("tmdb_id")
            )
            db_id = db_id or item.get("db_id", "")
            instance = (
                item.get("instance_name")
                or item.get("config_instance_name")
                or "Unknown Instance"
            )
            grouped.setdefault(instance, []).append(f"{title}{year}\t{db_id}")
        for instance, lines in grouped.items():
            text = "\n".join(lines)
            fields.extend(chunk_code_fields(instance, text))
        if fields:
            dry_run = any(item.get("dry_run") for item in o)
            if dry_run:
                summary = "🔍 The following items were flagged as removed from TMDB/TVDB and would be deleted."
            else:
                summary = "🧹 The following items were deleted as they were removed from TMDB/TVDB."
            fields.insert(0, {"name": "Summary", "value": f"```{summary}```"})
        return fields

    def fmt_nohl(o: Any) -> List[Dict[str, Any]]:
        """Format nohl output for Discord embeds — counts only.

        The per-title/season/episode listing is a scan finding, not a change
        this run made; it stays in the run log.
        """
        scanned = o.get("scanned", {}) or {}
        movie_titles = 0
        series_titles = 0
        for results in scanned.values():
            movie_titles += len(results.get("movies", []) or [])
            series_titles += len(results.get("series", []) or [])
        summary = o.get("summary", {}) or {}
        # These four are FILE counts, not title counts — see nohl.build_summary.
        movie_files = summary.get("total_scanned_movies", 0)
        episode_files = summary.get("total_scanned_series", 0)
        searched_movies = summary.get("total_resolved_movies", 0)
        searched_episodes = summary.get("total_resolved_series", 0)

        if not any((movie_titles, series_titles, searched_movies, searched_episodes)):
            return [{"name": "✅ All scanned files are hardlinked!", "value": ""}]

        lines = [
            f"Movies: {movie_titles} titles, {movie_files} non-hardlinked files",
            f"Series: {series_titles} titles, {episode_files} non-hardlinked "
            "episode files",
            f"Searched: {searched_movies} movies, {searched_episodes} episodes",
        ]
        return [{"name": "Summary", "value": "```" + "\n".join(lines) + "```"}]

    def fmt_upgradinatorr(o: Any) -> List[Dict[str, Any]]:
        """Format upgradinatorr output for Discord embeds.

        Grabs are listed — they are what the run changed. The queue sections
        are a tally off the same QUEUE_REPORT_SECTIONS the run log renders, so
        the two can't drift; the per-item rows and the *arr's own rejection
        text are log-level detail.
        """
        fields: List[Dict[str, Any]] = []
        for inst, data in o.items():
            srv = data.get("server_name", inst)
            instance_data = data.get("data", []) or []
            lines: List[str] = []
            for item in instance_data:
                dl = item.get("download") or {}
                if not dl:
                    continue
                title = item.get("title", "Unknown")
                year = f" ({item.get('year')})" if item.get("year") else ""
                lines.append(f"{title}{year}")
                for name, score in dl.items():
                    lines.append(f"\t{name}")
                    lines.append(f"\tCF Score: {score}")
                lines.append("")
            if lines:
                fields.extend(chunk_code_fields(srv, "\n".join(lines).strip()))
            for state, tag, note, _level in QUEUE_REPORT_SECTIONS:
                item_count = 0
                total = 0
                for item in instance_data:
                    entries = [
                        e
                        for e in (item.get("queue_imports") or [])
                        if e.get("state") == state
                    ]
                    if not entries:
                        continue
                    item_count += 1
                    total += len(entries)
                if not item_count:
                    continue
                fields.append(
                    {
                        "name": f"{srv} — {tag.lower()}",
                        "value": f"```{queue_report_tally(total, item_count, note)}```",
                    }
                )
        return fields

    def fmt_labelarr(o: Any) -> List[Dict[str, Any]]:
        """Format labelarr output for Discord embeds.

        Label changes stay listed; chunked so a long list can't blow the
        1024-char embed field limit.
        """
        fields: List[Dict[str, Any]] = []
        summary = f"Synced {len(o)} items across configured Plex libraries."
        fields.append({"name": "Summary", "value": f"```{summary}```"})
        label_changes: Dict[Tuple[str, str], List[str]] = {}
        for item in o:
            for label, action in item["add_remove"].items():
                label_changes.setdefault((label, action), []).append(
                    f"{item['title']} ({item['year']})"
                )
        for (label, action), items in label_changes.items():
            verb = "added to" if action == "add" else "removed from"
            fields.extend(
                chunk_code_fields(
                    f"Label: `{label}` has been {verb}:", "\n".join(items)
                )
            )
        return fields

    def fmt_nestarr(o: Any) -> List[Dict[str, Any]]:
        """Format Nestarr scan issues for Discord embeds — counts only.

        The per-issue listing is a scan finding, not a change this run made.
        """
        issues = o.get("issues", []) if isinstance(o, dict) else (o or [])
        if not issues:
            return [
                {
                    "name": "Summary",
                    "value": "No unmatched, nested, or stray media issues found.",
                }
            ]

        type_labels = {
            "arr_not_in_plex": "In ARR, Not in Plex",
            "plex_not_in_arr": "In Plex, Not in ARR",
            "stray_folder": "Stray Folder",
            "stray_file": "Stray File",
            "extra_video_in_folder": "Extra Video Files",
        }
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for issue in issues:
            grouped.setdefault(issue.get("type", "unknown"), []).append(issue)

        lines = [f"Total issues: {len(issues)}"]
        lines.extend(
            f"{type_labels.get(t, t.replace('_', ' ').title())}: {len(items)}"
            for t, items in sorted(grouped.items())
        )
        return [{"name": "Summary", "value": "```" + "\n".join(lines) + "```"}]

    def fmt_jduparr(o: Any) -> List[Dict[str, Any]]:
        """Format jduparr output for Discord flat messages — counts only.

        The per-file jdupes output is log detail; the relink counts are what
        the run changed.
        """
        results: List[Dict[str, Any]] = []
        for item in o:
            source_dirs = item.get("source_dirs")
            source_dir = item.get("source_dir", "Unknown")
            field_message = item.get("field_message", "")
            sub_count = item.get("sub_count", 0)
            linked_count = item.get("linked_count", 0)
            if isinstance(source_dirs, list) and source_dirs:
                dir_label = ", ".join(
                    os.path.basename(os.path.normpath(path)) or path
                    for path in source_dirs
                )
            else:
                dir_label = os.path.basename(os.path.normpath(source_dir)).capitalize()
            header = f"_\nSource Directory: '__**{dir_label}**__'\n{field_message}"
            footer = "\nPowered by: CHUB"
            lines = [f"\tRelink candidates in '{dir_label}': {sub_count}"]
            if linked_count:
                lines.append(f"\tItems re-linked in '{dir_label}': {linked_count}")
            if item.get("error"):
                lines.append(f"\tError: {item['error']}")
            results.extend(chunk_flat_content(header, "\n".join(lines), footer))
        return results

    def fmt_poster_cleanarr(o: Any) -> List[Dict[str, Any]]:
        """Format poster_cleanarr output for Discord embeds."""
        fields: List[Dict[str, Any]] = []
        mode = o.get("mode", "unknown").capitalize()
        fields.append({"name": "Mode", "value": mode, "inline": True})

        bloat = o.get("bloat", {})
        if bloat.get("count", 0) > 0:
            fields.append(
                {
                    "name": "Bloat Images",
                    "value": f"{bloat['count']} files ({bloat.get('size_human', '0 B')})",
                    "inline": True,
                }
            )

        orphaned = o.get("orphaned", {})
        if orphaned.get("count", 0) > 0:
            fields.append(
                {
                    "name": "Orphaned Posters",
                    "value": str(orphaned["count"]),
                    "inline": True,
                }
            )

        pt = o.get("photo_transcoder", {})
        if pt.get("count", 0) > 0:
            fields.append(
                {
                    "name": "PhotoTranscoder",
                    "value": f"{pt['count']} files ({pt.get('size_human', '0 B')})",
                    "inline": True,
                }
            )

        maintenance = o.get("maintenance", {})
        if maintenance:
            lines = []
            for task, status in maintenance.items():
                icon = "✅" if status == "success" else "❌"
                lines.append(f"{icon} {task}: {status}")
            fields.append(
                {
                    "name": "Plex Maintenance",
                    "value": "\n".join(lines),
                }
            )

        elapsed = o.get("elapsed", 0)
        fields.append({"name": "Duration", "value": f"{elapsed}s", "inline": True})
        return fields

    def fmt_plex_maintenance(o: Any) -> List[Dict[str, Any]]:
        """Format plex_maintenance output for Discord embeds."""
        fields: List[Dict[str, Any]] = []

        pt = o.get("photo_transcoder", {})
        if pt.get("count", 0) > 0:
            fields.append(
                {
                    "name": "PhotoTranscoder",
                    "value": f"{pt['count']} files ({pt.get('size_human', '0 B')})",
                    "inline": True,
                }
            )

        maintenance = o.get("maintenance", {})
        if maintenance:
            lines = []
            for task, status in maintenance.items():
                icon = "✅" if status == "success" else "❌"
                lines.append(f"{icon} {task}: {status}")
            fields.append(
                {
                    "name": "Plex Maintenance",
                    "value": "\n".join(lines),
                }
            )

        elapsed = o.get("elapsed", "")
        if elapsed:
            fields.append({"name": "Duration", "value": str(elapsed), "inline": True})
        return fields

    def fmt_version_check(o: dict) -> list:

        fields = [
            {"name": "Update Available", "value": "🚨 A new update is available!"},
            {"name": "Your Version", "value": o.get("local_version", "")},
            {"name": "Latest Version", "value": o.get("remote_version", "")},
        ]
        return fields

    def fmt_error_notify(o: dict) -> list:
        fields = [
            {"name": "Error", "value": o.get("error_message", "")},
            {"name": "Module", "value": o.get("source_module", "")},
        ]
        tb = o.get("traceback")
        if tb:
            if len(tb) > 1800:
                tb = tb[:1800] + "\n...truncated..."
            fields.append({"name": "Traceback", "value": f"```{tb}```"})
        return fields

    def fmt_border_replacerr(o: Any) -> List[Dict[str, Any]]:
        """Format border_replacerr output for Discord embeds."""
        fields: List[Dict[str, Any]] = []
        fields.append(
            {
                "name": "Processed",
                "value": str(o.get("processed", 0)),
                "inline": True,
            }
        )
        fields.append(
            {
                "name": "Skipped",
                "value": str(o.get("skipped", 0)),
                "inline": True,
            }
        )
        if o.get("replaced"):
            fields.append(
                {
                    "name": "Borders replaced",
                    "value": str(o["replaced"]),
                    "inline": True,
                }
            )
        if o.get("removed"):
            fields.append(
                {
                    "name": "Borders removed",
                    "value": str(o["removed"]),
                    "inline": True,
                }
            )
        if o.get("active_holiday"):
            fields.append(
                {
                    "name": "Holiday",
                    "value": str(o["active_holiday"]),
                    "inline": False,
                }
            )
        return fields

    def fmt_sync_gdrive(o: Any) -> List[Dict[str, Any]]:
        """Format sync_gdrive output for Discord embeds.

        Shape expected on `o`:
            - total, succeeded, failed, elapsed
            - items: list of {owner, counters: {copied, deleted, updated,
              renamed}, success, file_count, ...}
            - agg_counters: aggregate {copied, deleted, updated, renamed}

        The notification surfaces what actually moved on disk this run.
        Per-folder file_count totals (the disk-wide size of each folder)
        are intentionally hidden — they're not delta information and
        used to mislead users into thinking a clean re-sync had
        transferred tens of thousands of files.
        """
        fields: List[Dict[str, Any]] = []
        fields.append(
            {
                "name": "Folders",
                "value": f"{o.get('succeeded', 0)} / {o.get('total', 0)}",
                "inline": True,
            }
        )
        if o.get("failed"):
            fields.append(
                {
                    "name": "Failed",
                    "value": str(o["failed"]),
                    "inline": True,
                }
            )
        if o.get("elapsed"):
            fields.append(
                {
                    "name": "Elapsed",
                    "value": str(o["elapsed"]),
                    "inline": True,
                }
            )

        agg = o.get("agg_counters") or {}
        for label, key in (
            ("Copied", "copied"),
            ("Deleted", "deleted"),
            ("Updated", "updated"),
            ("Renamed", "renamed"),
        ):
            if agg.get(key):
                fields.append({"name": label, "value": str(agg[key]), "inline": True})

        items = o.get("items") or []
        # Only surface folders that actually had activity. Folders that
        # were already in sync would otherwise crowd out the meaningful
        # rows and inflate the truncation count.
        active = [it for it in items if any((it.get("counters") or {}).values())]
        if active:
            lines = []
            for it in active[:15]:
                c = it.get("counters") or {}
                parts = []
                for label, key in (
                    ("copied", "copied"),
                    ("deleted", "deleted"),
                    ("updated", "updated"),
                    ("renamed", "renamed"),
                ):
                    if c.get(key):
                        parts.append(f"{c[key]} {label}")
                lines.append(f"• **{it.get('owner', '?')}** — {', '.join(parts)}")
            if len(active) > 15:
                lines.append(f"…and {len(active) - 15} more with activity")
            fields.append(
                {
                    "name": "Activity by folder",
                    "value": "\n".join(lines),
                    "inline": False,
                }
            )
        else:
            fields.append(
                {
                    "name": "Activity",
                    "value": "All folders in sync — no files transferred.",
                    "inline": False,
                }
            )
        return fields

    def fmt_asset_renamerr(o: Any) -> List[Dict[str, Any]]:
        """Format asset_renamerr output for Discord embeds.

        Input is ``{image_type: [{title, year, source, applied, reason}, ...]}``.
        Applied assets are listed — that is what changed; skipped ones collapse
        to a count, since their per-entry reasons are log detail.
        """
        fields: List[Dict[str, Any]] = []
        for image_type, entries in (o or {}).items():
            if not entries:
                continue
            applied = [e for e in entries if e.get("applied")]
            lines = [f"{len(applied)}/{len(entries)} applied"]
            for entry in applied:
                title = entry.get("title") or ""
                year = entry.get("year")
                disp = f"{title} ({year})" if year else title
                src = entry.get("source")
                lines.append(f"✓ {disp}{f' [{src}]' if src else ''}")
            skipped = len(entries) - len(applied)
            if skipped:
                lines.append(f"{skipped} skipped")
            fields.extend(chunk_code_fields(image_type.capitalize(), "\n".join(lines)))

        if not fields:
            fields = [{"name": "No assets were applied.", "value": ""}]
        return fields

    registry: Dict[str, Dict[str, Any]] = {
        "poster_renamerr": {"formatter": fmt_poster_renamerr, "type": "embedded"},
        "asset_renamerr": {"formatter": fmt_asset_renamerr, "type": "embedded"},
        "renameinatorr": {"formatter": fmt_renameinatorr, "type": "embedded"},
        "health_checkarr": {"formatter": fmt_health_checkarr, "type": "embedded"},
        "nohl": {"formatter": fmt_nohl, "type": "embedded"},
        "upgradinatorr": {"formatter": fmt_upgradinatorr, "type": "embedded"},
        "labelarr": {"formatter": fmt_labelarr, "type": "embedded"},
        "nestarr": {"formatter": fmt_nestarr, "type": "embedded"},
        "jduparr": {"formatter": fmt_jduparr, "type": "flat"},
        "poster_cleanarr": {"formatter": fmt_poster_cleanarr, "type": "embedded"},
        "plex_maintenance": {"formatter": fmt_plex_maintenance, "type": "embedded"},
        "border_replacerr": {"formatter": fmt_border_replacerr, "type": "embedded"},
        "sync_gdrive": {"formatter": fmt_sync_gdrive, "type": "embedded"},
        "version_check": {"formatter": fmt_version_check, "type": "embedded"},
        "error_notify": {"formatter": fmt_error_notify, "type": "embedded"},
    }
    # Extension modules contribute their own formatters (empty on main). Lazy
    # import: this module loads during core init, before extensions are ready.
    from backend.extensions import extension_notification_formatters

    registry.update(extension_notification_formatters())
    formatter_entry = registry.get(config.module_name)
    if not formatter_entry:
        return {}, True
    formatter = formatter_entry["formatter"]
    output_type = formatter_entry["type"]
    formatted_output = formatter(output)
    if output_type == "flat":
        return formatted_output, True
    parts = split_fields(formatted_output)
    return _collapse_large_notification(parts, formatted_output), True

# Modules

CHUB ships twelve modules. Each one is a scheduled chore you can also run on demand. Every module has its own section in `config.yml` and its own page under **Settings → Modules** in the UI.

Every module supports:

- **Dry run** — when `dry_run: true`, the module logs what it *would* do without making changes. Turn this on the first time you try a module.
- **Log level** — `debug` / `info` / `warning` / `error`, per module. Default is `info`. Flip to `debug` while you're diagnosing a problem, then back.
- **Cancel from the UI** — Settings → Jobs → click the running job → **Cancel**. Eleven of the twelve modules stop cleanly on the next iteration (see each module below). `border_replacerr` is the exception — it runs to completion today; restart the container if you truly need to interrupt it.
- **Run history** — visible in **Settings → Jobs** with full log output.

Below, each module has four quick sections: what it does, what to configure, whether it can be cancelled mid-run, and a gotcha or two.

## `poster_renamerr`

**What it does.** Walks your Kometa (or other) asset folders, matches each image against your Radarr/Sonarr/Plex libraries, renames the files to match, and copies/moves/hardlinks them into your destination tree. Can optionally chain into `border_replacerr` and `poster_cleanarr` as a post-hook.

**Configure:** `source_dirs`, `destination_dir`, and at least one entry in `instances` (Radarr/Sonarr/Plex). Set `action_type` to `copy`, `move`, or `hardlink` depending on how you want files placed. `hardlink` only works when source and destination are on the same filesystem.

**Cancellable:** yes.

**Gotcha:** if nothing seems to be moving, check that `dry_run` is off, that `destination_dir` is writable by your `PUID`/`PGID`, and that `action_type: hardlink` isn't crossing filesystems.

## `border_replacerr`

**What it does.** Re-applies a brand or holiday border to every poster in your tree. Strips any existing border and paints a new one of `border_width` pixels using a random color from `border_colors` — or a holiday palette if today falls within a holiday window.

**Configure:** `source_dirs`, `destination_dir`, `border_width`, `border_colors`, optional `holidays` entries. Each holiday's `schedule` takes `MM-DD:MM-DD` (year-agnostic), e.g. `"10-01:10-31"` for Halloween.

**Cancellable:** not yet. If you start a big run and need to stop it, you'll need to restart the container.

**Gotcha:** if two holidays overlap, whichever is listed first wins.

## `poster_cleanarr`

**What it does.** Removes stale / orphaned poster metadata from Plex's internal folder — optionally empties the trash, cleans bundles, and optimizes the Plex database.

**Configure:** `plex_path` (the Plex `Metadata/` directory as seen from inside the CHUB container), at least one `plex` instance, and a `mode`. The valid modes are `report` (dry run — lists orphaned images without touching them), `move` (relocates them into a `Poster Cleanarr Restore` folder so you can sanity-check before deleting), `remove` (deletes outright), `restore` (moves anything in the restore folder back), `clear` (deletes the restore folder), and `nothing` (skips image work but still runs `empty_trash` / `clean_bundles` / `optimize_db` if those are enabled). Start with `report`, move to `move`, then `remove` once you trust it.

**Cancellable:** yes.

**Gotcha:** `plex_path` must be a filesystem path (e.g. `/plex-config/Library/Application Support/Plex Media Server/Metadata`), not a URL.

## `labelarr`

**What it does.** Mirrors tags in Radarr/Sonarr into Plex labels. If you tag an item `favorite` in Sonarr, it shows up with the `favorite` label in the Plex library you've mapped.

**Configure:** one or more `mappings`, each linking an ARR instance and a list of tag names to one or more Plex libraries.

**Cancellable:** yes.

**Gotcha:** label updates are applied in batch — if you untag a large number of items in the ARR, expect the corresponding Plex labels to update on the next run, not instantly.

## `jduparr`

**What it does.** Finds duplicate files across your media tree by content hash. Persists hashes to a database so repeat runs are incremental instead of re-hashing everything.

**Configure:** `source_dirs`, `hash_database` (a path you want CHUB to write the hash index to).

**Cancellable:** yes.

**Gotcha:** the first run on a large library takes hours. Subsequent runs are fast because only new/changed files are rehashed. `hash_database` can't contain null bytes or start with `-` (this is a safety check — see [Troubleshooting](Troubleshooting) if you hit it).

## `nohl`

**What it does.** Finds media files that aren't hardlinked to your downloader's completed directory, which typically means a broken rename or a file that was re-imported without a hardlink. Optionally re-queues an upgrade search in the ARR to fix them.

**Configure:** `source_dirs` (your library roots), at least one ARR instance. `exclude_profiles`, `exclude_movies`, `exclude_series` let you skip things you don't care about.

**Cancellable:** yes.

## `unmatched_assets`

**What it does.** Reports media items that don't have a matching poster in your renamed tree. Runs standalone or as a post-hook on `poster_renamerr` (set `report_unmatched_assets: true` on `poster_renamerr` to chain them).

**Cancellable:** yes.

## `upgradinatorr`

**What it does.** Picks a fixed number of items per ARR instance that haven't been searched recently, and fires an upgrade search on them. Tags items after searching so it doesn't pick the same ones again right away.

**Configure:** one entry per ARR instance in `instances_list`, each with a `count`, a `tag_name`, an `ignore_tag`, and a `search_mode` (`upgrade`, `missing`, or `cutoff`).

**Cancellable:** yes.

**Gotcha:** Lidarr is fully supported — album search, artist grouping, all three search modes.

## `renameinatorr`

**What it does.** Walks Radarr/Sonarr and applies the ARR's own naming scheme to existing files — useful after you change your naming template and don't want to re-import everything.

**Configure:** one or more ARR instances, a `count` per run, optionally `rename_folders: true` and `enable_batching: true`.

**Cancellable:** yes.

## `health_checkarr`

**What it does.** Polls each ARR's built-in health / queue / missing lists and surfaces problems via notification. `report_only: true` turns it into a pure notifier (no remediation).

**Cancellable:** yes.

## `nestarr`

**What it does.** Moves items between split Plex libraries (e.g. a "Movies" and a "Movies 4K" library) based on ARR path mappings. Reads an item's path from the ARR, translates it into its Plex path, and tells Plex which library it belongs in.

**Configure:** `mappings`, each with a `path_mapping` (`arr_prefix` → `plex_prefix`) and a list of Plex libraries.

**Cancellable:** yes.

## `sync_gdrive`

**What it does.** Pulls poster assets from Google Drive folders into a local directory, using `rclone` under the hood. Supports OAuth tokens or a service-account JSON file.

**Configure:** either (`client_id` + `client_secret` + `token`) or (`gdrive_sa_location`), plus at least one entry in `gdrive_list` (folder ID → local path).

**Cancellable:** yes.

**Gotcha:** `sync_location`, `gdrive_sa_location`, and folder IDs can't contain null bytes or start with `-` (a safety check to keep user input from being interpreted as rclone flags).

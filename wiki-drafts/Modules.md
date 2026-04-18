# Modules

CHUB ships 12 scheduled / on-demand modules. Each one extends `ChubModule` (`backend/util/base_module.py`) and is registered in `backend/modules/__init__.py`.

All modules share:

- A `dry_run` flag — when `true`, the module logs what it *would* do without making changes.
- A `log_level` — per-module override (`debug` / `info` / `warning` / `error`).
- Cancellation via `DELETE /api/modules/{name}/execution/{job_id}` (see status per module below).
- Run history visible in the UI (**Settings → Jobs**) and at `GET /api/jobs`.

> **CHUB-era additions.** Cooperative cancellation, argument-smuggling / path-safety guards, full Lidarr support in `upgradinatorr`, webhook origin tracking, and the path-injection guard on `poster_cleanarr`'s `set-active` endpoint were all added in the CHUB audit pass on top of the original DAPS module set. Each module's section below flags its CHUB additions explicitly; see [Credits](Credits) for the full list.

---

## `poster_renamerr`

Renames posters in your source tree to match Plex/ARR item filenames and copies/moves/hardlinks them into a destination tree.

**Does:** walks `source_dirs` (typically Kometa assets), matches each image against your Radarr/Sonarr/Plex libraries, and writes a normalized filename into `destination_dir`. Can run `border_replacerr` and `poster_cleanarr` as post-hooks.

**Required config:** `source_dirs`, `destination_dir`, at least one entry in `instances`.

**Cancellation:** ❌ not yet wired.

---

## `poster_cleanarr`

Removes stale / orphaned posters from Plex's internal metadata and optional photo-transcoder cache.

**Does:** connects to Plex, compares `Metadata/` entries against your current library, deletes anything orphaned. Optional `empty_trash`, `clean_bundles`, `optimize_db` steps. Supports `mode: report` for a dry-run summary.

**Required config:** `plex_path` (path to the Plex metadata directory on disk), at least one `plex` instance.

**Cancellation:** ❌ not yet wired.

**CHUB additions:** path-injection guard on `POST /api/posters/{poster_id}/set-active`; `set-active` endpoint moved above the `/{poster_id}` catch-all so explicit metadata routes resolve correctly.

---

## `border_replacerr`

Re-applies a brand/holiday border to every poster in your tree.

**Does:** reads `source_dirs`, for each image strips any existing border and paints a new border of `border_width` using a random color from `border_colors` (or a holiday palette if a matching `holidays` entry's schedule window is active today). Writes to `destination_dir`.

**Holidays:** the `schedule` field takes `MM-DD:MM-DD` (year-agnostic). During the window, `holidays[N].colors` replaces the default palette.

**Cancellation:** ❌ not yet wired.

---

## `labelarr`

Syncs tags from Radarr/Sonarr → labels in Plex.

**Does:** for each mapping, reads items from the ARR instance with one of the configured tags, finds the matching Plex item, and calls `addLabel(label)` / `removeLabel(label)` so Plex labels mirror the ARR tag state.

**Gotcha:** labelarr uses batched updates — it searches Plex once per item and applies every add/remove to the same object (sequential searches can return stale state).

**Cancellation:** ❌ not yet wired.

**CHUB additions:** bulk sync endpoint `POST /api/labelarr/bulk-sync` accepts up to 1000 media IDs per request; **Label Sync** page in the UI wraps it.

---

## `jduparr`

Finds and reports duplicate files across your media tree using content hashing.

**Does:** hashes files in `source_dirs` (SHA-based), persists hashes to `hash_database` for incremental runs, and reports duplicates via module logs + notifications.

**Required config:** `hash_database` (safe path — no null bytes, no leading `-`), `source_dirs`.

**Cancellation:** ✅ cooperatively cancellable.

**CHUB additions:** cooperative cancellation wired; `hash_database` path validation (rejects null bytes and values starting with `-`) to prevent arg-smuggling.

---

## `nohl`

Finds media files on your library volumes that aren't hardlinked (i.e. not shared with the ARR's "completed downloads" source), then optionally triggers a re-search in the ARR to fix them.

**Does:** for each path in `source_dirs`, walks the tree, skips files whose inode count > 1, and calls out to the configured ARR instance to re-queue. Honors `exclude_profiles`, `exclude_movies`, `exclude_series`.

**Cancellation:** ✅ cooperatively cancellable.

**CHUB additions:** cooperative cancellation wired.

---

## `unmatched_assets`

Reports media items that have no matching poster asset in your renamed tree.

**Does:** walks `destination_dir` of `poster_renamerr`, cross-references against configured ARR instances, logs anything unmatched. Useful as a companion to `poster_renamerr` (set `report_unmatched_assets: true` on poster_renamerr to chain them).

**Cancellation:** ✅ cooperatively cancellable.

**CHUB additions:** cooperative cancellation wired.

---

## `upgradinatorr`

Picks N items per ARR instance that haven't been searched recently and triggers an upgrade search.

**Does:** for each entry in `instances_list`, selects `count` items matching `search_mode`:

- `upgrade` — items below cutoff
- `missing` — unmonitored-but-wanted / missing-only
- `cutoff` — items already at cutoff but eligible for a different release

Tags items with `tag_name` after searching so they aren't picked again immediately; ignores anything carrying `ignore_tag`. Full Lidarr support (album search + artist grouping).

**Cancellation:** ✅ cooperatively cancellable.

**CHUB additions:** cooperative cancellation wired; full Lidarr support (album search, artist grouping, wanted/missing/cutoff modes).

---

## `renameinatorr`

Walks Radarr/Sonarr and applies the ARR's own naming scheme to existing files (useful after changing your naming profile without wanting to re-import).

**Does:** for each instance, selects up to `count` items, calls the ARR's rename endpoint, optionally renames folders too. `enable_batching` batches API calls.

**Cancellation:** ❌ not yet wired.

---

## `health_checkarr`

Walks each ARR's built-in health / queue / missing lists and surfaces problems.

**Does:** polls every instance in `instances`, aggregates health warnings, sends a notification on any changes. `report_only: true` suppresses remediation and just reports.

**Cancellation:** ❌ not yet wired.

---

## `nestarr`

Moves Plex items between libraries based on ARR path mappings (useful for "4K" / "SD" split libraries).

**Does:** for each mapping, reads items from the ARR instance, uses `path_mapping` to translate ARR paths → Plex paths, and moves items between `plex_instances.library_names` accordingly.

**Cancellation:** ❌ not yet wired.

---

## `sync_gdrive`

Pulls poster assets from Google Drive folders into a local directory using `rclone` under the hood.

**Does:** for each entry in `gdrive_list`, syncs `<folder_id>` → `<location>` via rclone with OAuth or a service-account file. Validates paths (no null bytes, no leading `-`) to prevent arg-smuggling into rclone.

**Required config:** either `client_id` + `client_secret` + `token`, or `gdrive_sa_location` (service account JSON), plus at least one `gdrive_list` entry.

**Cancellation:** ✅ cooperatively cancellable.

**CHUB additions:** cooperative cancellation wired; path validation on `sync_location`, `gdrive_sa_location`, and folder IDs (rejects null bytes and values starting with `-`) to prevent arg-smuggling into rclone.

---

## Writing a new module

1. Create `backend/modules/my_module.py`:
   ```python
   from backend.util.base_module import ChubModule

   class MyModule(ChubModule):
       def run(self):
           self.logger.info("starting")
           for item in self.work():
               if self.is_cancelled():
                   self.logger.info("cancelled")
                   return
               self.process(item)
   ```

2. Add a Pydantic config model to `backend/util/config.py` and attach it to `ChubConfig`:
   ```python
   class MyModuleConfig(BaseModel):
       log_level: str = "info"
       dry_run: bool = False
       # ...

   class ChubConfig(BaseModel):
       ...
       my_module: MyModuleConfig = Field(default_factory=MyModuleConfig)
   ```

3. Register the class in `backend/modules/__init__.py`:
   ```python
   from backend.modules.my_module import MyModule
   MODULES["my_module"] = MyModule
   ```

4. Rebuild the container. The scheduler, job processor, and UI pick up the new module automatically.

# API reference

CHUB exposes a REST API so you can automate from scripts. Everything lives under `/api/*`. Every authenticated endpoint requires a JWT in `Authorization: Bearer <token>`; server-sent-event streams accept `?token=<jwt>` as a fallback because browsers can't set headers on `EventSource`.

This page covers the endpoints most users reach for. For the complete list, visit the live OpenAPI docs at `http://<your-host>:8000/docs` once CHUB is running — FastAPI generates them from the source and they're always in sync.

## Conventions

Base URL: `http://<host>:8000`. Request bodies are JSON. Errors come back as `{"detail": "message"}` with conventional HTTP status codes. Timestamps are ISO-8601 UTC unless noted. Endpoints that paginate accept `limit` and `offset` query parameters.

## Auth — `/api/auth`

- `GET /api/auth/status` — returns `{"configured": true|false}`. Unauthenticated.
- `POST /api/auth/setup` — first-run only; body `{ "username": "...", "password": "..." }`; returns `{ "username": "...", "token": "<jwt>" }`. Rejected if an admin already exists.
- `POST /api/auth/login` — body `{ "username": "...", "password": "..." }`; returns `{ "token": "<jwt>", "expires_at": "..." }`. Rate-limited: roughly one attempt every 5 seconds with a burst of 5; exceed it and you'll get `429`.

## Modules — `/api/modules`

- `GET /api/modules` — list every module with its enabled flag, last run, and current status.
- `GET /api/modules/run-states` — snapshot of every module's run state (idle / running / queued / error).
- `GET /api/modules/events` — server-sent event stream; emits a JSON payload whenever a module's run state changes. Auth via `?token=<jwt>`. The frontend auto-reconnects.
- `GET /api/modules/{name}` — full state for one module: config, last run, current run (if any), schedule.
- `GET /api/modules/{name}/schema` — JSON schema for the module's config, used to render settings forms.
- `PUT /api/modules/{name}/config` — replace the module's config block; validated before persisting.
- `POST /api/modules/{name}/execute` — queue a manual run. Returns `{"job_id": ...}`. Body can carry one-shot overrides.
- `GET /api/modules/{name}/status/{job_id}` — live status of a queued/running job.
- `DELETE /api/modules/{name}/execution/{job_id}` — request cooperative cancellation. The job's cancel event is set; 11 of the 12 modules (everything except `border_replacerr`) check the event and exit cleanly on the next iteration.
- `GET /api/modules/{name}/history?limit=25` — recent runs.
- `POST /api/modules/{name}/test` — connectivity test for modules that need external services.

## Media — `/api/media`

- `GET /api/media/search?type=movie&limit=50&offset=0` — unified search across every configured Radarr/Sonarr/Lidarr. Supports `type`, `status`, `tag`, `sort`, `order`.
- `GET /api/media/stats?period=30d` — counters filtered by `created_at`; `period` is `7d`, `30d`, `90d`, or `all`.
- `GET /api/media/duplicates?similarity=0.8` — duplicate groups. `similarity=1.0` is exact-title; lower values use fuzzy matching.
- `POST /api/media/duplicates/{group_id}/resolve` — resolve a duplicate group. Body: `{ "keepId": "...", "removeIds": ["..."], "deleteFiles": true, "addImportExclusion": true }`.
- `GET /api/media/low-rated?max_rating=5.0` — items below a rating threshold.
- `GET /api/media/incomplete-metadata?fields=rating,studio,language,genre` — items missing any of the requested fields.
- `POST /api/media/import` — batch-add to Radarr/Sonarr. Body: `{ "instance": "radarr_main", "items": [{ "tmdb_id": 603, "quality_profile_id": 1, "root_folder": "/media/movies" }] }`. Each item is validated before insert.
- `POST /api/media/refresh` — refresh the media cache from your ARRs.
- `POST /api/media/scan` — scan for new content.
- `POST /api/media/export` — export the current filter as a list.
- `POST /api/media/fix-metadata` — run a bulk metadata fix over the currently filtered set.
- `GET /api/media/{media_id}` — single media record.
- `PUT /api/media/{media_id}/metadata` — inline metadata edit. Writes a `media_edit_history` row per field changed.
- `DELETE /api/media/{media_id}?delete_files=true` — remove from the cache and optionally delete files.
- `POST /api/media/{media_id}/fix-metadata` — fix metadata for a single item.
- `GET /api/media/{media_id}/history` — audit trail of edits.
- `GET /api/media/{media_id}/import-exclusion` — query whether this item is on the ARR's import exclusion list.
- `GET /api/media/collections` — list collections.
- `POST /api/media/collections` — create a collection.
- `PUT /api/media/collections/{collection_id}` / `DELETE /api/media/collections/{collection_id}` — update or remove.
- `POST /api/media/collections/from-tag` — build a collection from an ARR tag. Body: `{ "tag": "favorites", "collection_name": "Favorites 2026" }`.

## Posters — `/api/posters`

- `GET /api/posters/list?type=movie&limit=100&offset=0` — paginated poster index with width/height if backfilled.
- `GET /api/posters/search` — text search against poster filenames.
- `GET /api/posters/browse` — directory-style browse of the poster tree.
- `GET /api/posters/stats` — counts, storage used, orphan report.
- `GET /api/posters/duplicates` — exact-hash duplicates.
- `POST /api/posters/duplicates/{group_id}/resolve` — pick which copy to keep.
- `GET /api/posters/low-resolution?min_width=1000` — posters below a resolution threshold.
- `GET /api/posters/added-since?cutoff=2026-01-01T00:00:00Z` — posters added since a cutoff.
- `POST /api/posters/backfill-dimensions?limit=500` — incremental: fills width/height for rows that lack them.
- `POST /api/posters/optimize` — optimize posters; `{ "mode": "report"|"optimize", "max_width": 2000, "format": "webp", "quality": 82, "paths": [...] }`.
- `POST /api/posters/auto-match` — batch-match unmatched posters to media.
- `POST /api/posters/upload` — upload one or more posters.
- `GET /api/posters/sources/gdrive/search` — search posters in configured GDrive sources.
- `GET /api/posters/sources/assets/search` — search posters in your local assets tree.
- `GET /api/posters/matched/stats` / `/unmatched/stats` / `/unmatched/details` — matched/unmatched reporting.
- `GET /api/posters/gdrive/stats` / `POST /api/posters/gdrive/sync` — inspect / trigger a sync.
- `GET /api/posters/{poster_id}` — single poster record.
- `GET /api/posters/{poster_id}/thumbnail?width=200` — generate (and cache) a JPEG thumbnail.
- `POST /api/posters/{poster_id}/download?size=500&format=webp&quality=80` — download the poster resized/re-encoded.
- `POST /api/posters/{poster_id}/sync-metadata` — sync the poster's metadata from its matched media record.
- `DELETE /api/posters/{poster_id}` — delete a single poster.

## Jobs — `/api/jobs`

- `GET /api/jobs?status=success&module=jduparr&limit=25&offset=0` — filter + paginate.
- `GET /api/jobs/stats` — counts by status / module over the last 30 days.
- `GET /api/jobs/{job_id}` — full job record.
- `GET /api/jobs/{job_id}/log-tail?bytes=10000` — tail of the job's log.
- `POST /api/jobs/{job_id}/retry` — re-queue a failed job.
- `DELETE /api/jobs/old?days=30` — purge completed jobs older than N days.
- `GET /api/jobs/webhook-origins?days=7` — aggregates the `origin` metadata on webhook-sourced jobs.

## Schedule — `/api/schedule`

- `GET /api/schedule` — current cron/interval rules per module.
- `POST /api/schedule` — replace the full schedule dict.
- `GET /api/schedule/{module_id}` — the current rule for one module.
- `DELETE /api/schedule/{module_id}` — remove the rule (module becomes manual-only).

## Instances — `/api/instances`

- `GET /api/instances` — all configured Radarr/Sonarr/Lidarr/Plex instances, secrets redacted.
- `GET /api/instances/types` / `GET /api/instances/types/{instance_type}/schema` — discover the schema for a given instance type.
- `GET /api/instances/health` — most-recent health probe per instance.
- `POST /api/instances/test` — test a candidate config before saving (body describes the instance).
- `POST /api/instances` — add an instance.
- `GET /api/instances/{instance_id}` / `PUT /api/instances/{instance_id}` / `DELETE /api/instances/{instance_id}` — CRUD by id.
- `PATCH /api/instances/{instance_id}` — partial update (e.g. toggle enabled).
- `POST /api/instances/{instance_id}/test` — force a connectivity test now.
- `POST /api/instances/{instance_id}/refresh` / `POST /api/instances/{instance_id}/sync` — kick cache refresh / full sync.
- `GET /api/instances/{instance_id}/stats` / `/health` / `/logs` — per-instance telemetry.
- `GET /api/plex/{instance}/libraries` — library sections for a named Plex instance.

## System — `/api`

- `GET /api/version` — CHUB version string.
- `GET /api/health` — unauthenticated liveness probe used by the container healthcheck; returns `{ "status": "ok" }`.
- `GET /api/directory` — walk the filesystem visible to the container (read-only) for path pickers.
- `POST /api/folder` — create a folder (used by the UI when setting up new destinations).
- `POST /api/test` — generic connectivity test helper.
- `POST /api/backup` — creates a zip of `config.yml` + `chub.db` and returns the download.
- `GET /api/backups` — list saved backups on disk.
- `POST /api/restore` — upload a backup zip to replace config + DB (destructive).
- `GET /api/system/health/snapshots?days=7` — time-series of scheduler probes.
- `GET /api/system/digest?days=7` — aggregated activity payload.
- `GET /api/system/cleanup-candidates` — orphaned posters, errored jobs, unmatched media/collections counts.

## Labelarr — `/api/labelarr`

- `POST /api/labelarr/sync` — sync labels for a single media item or a specific mapping. Body describes what to sync.
- `POST /api/labelarr/bulk-sync` — bulk version; body: `{ "media_ids": ["radarr_main:1", "radarr_main:2", ...] }` (cap 1000).

## Webhooks — `/api/webhooks`

See [Webhooks](Webhooks) for the full walkthrough. Five endpoints:

- `POST /api/webhooks/poster/add`
- `GET /api/webhooks/unmatched/status`
- `POST /api/webhooks/unmatched/process`
- `GET /api/webhooks/cleanarr/status`
- `POST /api/webhooks/cleanarr/process`

## Config — `/api/config`

- `GET /api/config` — full `config.yml` as JSON, secrets replaced by `********`.
- `POST /api/config` — write config. Fields still equal to `********` are kept from the on-disk value, so editing non-sensitive fields doesn't wipe your API keys.

## Logs — `/api/logs`

- `GET /api/logs` — list log files grouped by module.
- `GET /api/logs/{module_name}?bytes=50000` — tail of the module's latest log.
- `GET /api/logs/{module}/{filename}` — plain-text serve of a specific rotated log file.

## Notifications — `/api/notifications`

- `GET /api/notifications` — current notifications config (per module + `main`).
- `POST /api/notifications` — write config.
- `GET /api/notifications/{module_id}` — per-module notification config.
- `POST /api/notifications/test` — send a test notification.
- `DELETE /api/notifications/{module_id}/{service_type}` — remove one notification target.

## Nestarr — `/api/nestarr`

- `GET /api/nestarr/scan` / `GET /api/nestarr/results` — scan for nested-media issues.
- `POST /api/nestarr/preview` / `POST /api/nestarr/fix` — preview / apply fixes.

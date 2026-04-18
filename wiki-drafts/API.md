# API reference

All CHUB endpoints live under `/api/*`. Authenticated endpoints require a JWT in `Authorization: Bearer <token>`; EventSource streams accept `?token=<jwt>` as a fallback.

This page covers the ~40 most useful endpoints grouped by resource. For the full list, browse `backend/api/*.py` or hit the live OpenAPI docs at `/docs` (FastAPI's built-in UI).

---

## Conventions

- Base URL: `http://<host>:8000`
- Content type: `application/json` for request bodies
- Errors: `{"detail": "message"}` with conventional HTTP status codes
- Timestamps: ISO-8601 UTC unless noted
- Pagination: `limit` + `offset` query params where supported

---

## Auth (`/api/auth`)

### `GET /api/auth/status`
Returns whether CHUB has been configured with an admin user.
```json
{ "configured": true }
```

### `POST /api/auth/setup`
First-run only. Rejected if an admin already exists.
```json
// request
{ "username": "admin", "password": "hunter2" }
// response
{ "username": "admin", "token": "<jwt>" }
```

### `POST /api/auth/login`
Rate-limited: 1 req / 5 s, burst 5. Returns `429` when limiter trips.
```json
{ "username": "admin", "password": "hunter2" }
```
Response: `{ "token": "<jwt>", "expires_at": "..." }`

### `GET /api/auth/me`
```json
{ "username": "admin" }
```

---

## Modules (`/api/modules*`)

### `GET /api/modules`
Lists every registered module with enabled flag, last-run summary, and status.

### `GET /api/modules/run-states`
Snapshot of every module's current run state (idle / running / queued / error).

### `GET /api/modules/events` (SSE)
Server-sent event stream — pushes a JSON payload every time a module's run state changes. Auth via `?token=<jwt>` or `Authorization` header. Auto-reconnect is handled by the frontend hook `useModuleEvents`.

### `GET /api/modules/{name}`
Full state for a single module: config, last run, current run if any, schedule.

### `GET /api/modules/{name}/schema`
Pydantic-derived JSON schema for the module's config section — used by the settings UI to render forms.

### `PUT /api/modules/{name}/config`
Write the module's config section. Body is the full config for the module; validated before persisting.

### `POST /api/modules/{name}/execute`
Queue a manual run. Optional body overrides one-shot knobs (e.g. `{"target_paths": ["..."]}` for poster_cleanarr).
Returns `{ "job_id": "..." }`.

### `GET /api/modules/{name}/status/{job_id}`
Live status of a queued/running job.

### `DELETE /api/modules/{name}/execution/{job_id}`
Cooperative cancel. Sets the cancel event; modules that check `is_cancelled()` exit on the next iteration.

### `GET /api/modules/{name}/history?limit=25`
Recent runs for a single module.

### `POST /api/modules/{name}/test`
Connectivity test for modules that need external services (ARR, Plex, GDrive). Returns per-instance pass/fail.

---

## Media (`/api/media*`)

### `GET /api/media?type=movie&limit=50&offset=0`
Unified search across Radarr/Sonarr/Lidarr cache. Filters: `type`, `status`, `tag`, `sort`, `order`.

### `GET /api/media/{id}`
Single media record with edit history count, poster refs, tags.

### `GET /api/media/{id}/history`
Audit trail (`media_edit_history` rows) — each edit records field, old, new, edited_by, timestamp.

### `GET /api/media/stats?period=30d`
Library counters filtered by `created_at`. `period` accepts `7d`, `30d`, `90d`, `all`.

### `GET /api/media/duplicates?similarity=0.8`
Duplicate groups. `similarity=1.0` = exact title match, lower values use `difflib.SequenceMatcher` fuzzy matching.

### `POST /api/media/duplicates/{group_id}/resolve`
```json
{
  "keepId": "radarr_main:1234",
  "removeIds": ["radarr_4k:5678"],
  "deleteFiles": true,
  "addImportExclusion": true
}
```
Deletes from the ARR instance(s) and local cache.

### `GET /api/media/low-rated?max_rating=5.0`
Items below a rating threshold.

### `GET /api/media/incomplete-metadata?fields=rating,studio,language,genre`
Items with any empty / null value among the requested fields.

### `POST /api/media/import`
Batch-add to Radarr/Sonarr. Validates each ID via pre-lookup.
```json
{
  "instance": "radarr_main",
  "items": [
    { "tmdb_id": 603, "quality_profile_id": 1, "root_folder": "/media/movies" }
  ]
}
```
Response: `{ "added": [...], "existing": [...], "invalid": [...], "failed": [...] }`.

### `PUT /api/media/{id}`
Inline metadata edit. Writes `media_edit_history` row per field changed.

### `DELETE /api/media/{id}?delete_files=true`

### `GET /api/media/{id}/import-exclusion`
Queries the ARR for the item's import-list-exclusion status.

### `POST /api/media/collections/from-tag`
```json
{ "tag": "favorites", "collection_name": "Favorites 2026" }
```

---

## Posters (`/api/posters*`)

### `GET /api/posters?type=movie&limit=100&offset=0`
Paginated poster index with width/height if backfilled.

### `GET /api/posters/{id}/thumbnail?width=200`
Generates (and caches) a JPEG thumbnail for a poster.

### `POST /api/posters/{id}/download?size=500&format=webp&quality=80`
Returns the poster resized/re-encoded on the fly.

### `GET /api/posters/low-resolution?min_width=1000`
Posters below a resolution threshold — run the dimension backfill first.

### `GET /api/posters/added-since?cutoff=2026-01-01T00:00:00Z`
Posters with `created_at ≥ cutoff`.

### `POST /api/posters/backfill-dimensions?limit=500`
Incremental: fills `width` / `height` for poster_cache rows that lack them, using PIL.

### `POST /api/posters/optimize`
```json
{
  "mode": "optimize",
  "max_width": 2000,
  "format": "webp",
  "quality": 82,
  "paths": ["/posters/Movie (2020).jpg"]
}
```
`mode: "report"` = dry-run; `mode: "optimize"` performs rewrites.

### `GET /api/posters/stats`
Counts, totals, orphan report.

### `GET /api/posters/duplicates`
Exact-hash duplicates (no visual similarity yet).

---

## Jobs (`/api/jobs`)

### `GET /api/jobs?status=success&module=jduparr&limit=25&offset=0`
DB-level filtering + pagination.

### `GET /api/jobs/stats`
Counts by status / module over the last 30 days.

### `GET /api/jobs/{job_id}`
Full job record including payload and result.

### `GET /api/jobs/{job_id}/log-tail?bytes=10000`
Tail of the job's log file.

### `POST /api/jobs/{job_id}/retry`
Re-queue a failed job with the same payload.

### `DELETE /api/jobs/old?days=30`
Purge completed jobs older than N days.

### `GET /api/jobs/webhook-origins?days=7`
Aggregates the `origin` metadata on webhook-sourced jobs — who's calling what.

---

## Schedule (`/api/schedule*`)

### `GET /api/schedule`
Current cron/interval rules per module.

### `POST /api/schedule`
Replace the full schedule dict.

### `GET /api/schedule/next-runs`
Next fire time for every scheduled module.

### `DELETE /api/schedule/{module}`
Remove the rule (module becomes manual-only).

---

## Instances (`/api/instances*`)

### `GET /api/instances`
All configured Radarr/Sonarr/Lidarr/Plex instances, redacted.

### `GET /api/instances/health`
Most-recent health probe per instance.

### `POST /api/instances/{type}/{name}/test`
Force a connectivity test right now.

### `GET /api/instances/{type}/{name}/libraries` (Plex)
Library sections for the named Plex instance.

### `GET /api/instances/{type}/{name}/quality-profiles` (ARR)
### `GET /api/instances/{type}/{name}/root-folders` (ARR)
### `GET /api/instances/{type}/{name}/tags` (ARR)

---

## System (`/api/system*`)

### `GET /api/system/health/snapshots?days=7`
Time-series of scheduler probes — one row per instance per 6-hour tick.

### `GET /api/system/digest?days=7`
Aggregated activity payload: `media_added`, `job_counts`, `recent_failures`, `latest_instance_health`, `orphaned_posters`.

### `GET /api/system/cleanup-candidates`
Orphaned posters, errored jobs, unmatched media/collections counts.

### `POST /api/system/backup`
Creates a zip of `config.yml` + `chub.db`; returns the file download.

### `GET /api/system/backups`
List saved backups on disk.

### `POST /api/system/restore`
Upload a backup zip to replace config + DB (destructive).

### `GET /api/health`
Unauthenticated liveness probe. Returns `{ "status": "ok" }` — used by the container healthcheck.

---

## Labelarr (`/api/labelarr*`)

### `POST /api/labelarr/bulk-sync`
```json
{ "media_ids": ["radarr_main:1", "radarr_main:2", "..."] }
```
Enqueues a `labelarr_sync` job per id (cap: 1000).

---

## Webhooks (`/api/webhooks/*`)

See [Webhooks](Webhooks) for the full picture — endpoints, event types, shared-secret auth, origin tracking.

---

## Config (`/api/config`)

### `GET /api/config`
Full `config.yml` as JSON, with secrets replaced by `********`.

### `POST /api/config`
Write config. Fields still equal to `********` are preserved from the on-disk value.

---

## Logs (`/api/logs*`)

### `GET /api/logs`
List log files grouped by module.

### `GET /api/logs/{module_name}?bytes=50000`
Tail of the module's latest log.

### `GET /api/logs/{module}/{filename}`
Plain-text serve of a specific log file.

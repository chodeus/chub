# UI Guide

A guided tour of every CHUB page. Screenshots reference `images/<name>.png` placeholders — swap in real captures after Phase 7 lands.

---

## Dashboard

![Dashboard](images/dashboard-light.png)

The landing page shows an at-a-glance summary:

- **Greeting row** — "Hello, {user}!" + live/polling indicator + **New run** CTA
- **Quick Start cards** — 5 pastel-badged shortcuts: Run module, Browse media, Browse posters, Find duplicates, Inspect logs
- **Recent jobs** — 4 cards with the latest successful runs from `GET /api/jobs?status=success&limit=4`
- **Scheduler callout** — shows which module fires next and when
- **Module status grid** — running / idle / error indicators per module, pulled from SSE (`/api/modules/events`) with polling fallback

Any card clicking through to a module view carries its context (module, job_id) in the URL.

---

## Media

### `/media/search` — Search & browse

![Media search](images/media-search.png)

- Unified search across every configured Radarr/Sonarr/Lidarr
- Filters: type (movie / series / album), sort, order — persisted per-device in `localStorage['chub_media_search_filters']`
- Recent search history dropdown surfaces from `localStorage['chub_recent_searches']`
- Click any result to open the detail drawer

### `/media/manage` — Detail + editing

Per-item view. Inline **Edit** button opens `EditMediaModal` with fields for title, year, status, rating, studio, language, edition, genre. Saving writes through `PUT /api/media/{id}` and creates a `media_edit_history` row per changed field.

- **Delete** — confirmation modal with "Also delete files from disk" checkbox
- **Duplicates** — if the item is part of a duplicate group, a resolution panel appears with a side-by-side radio picker (keep this copy → remove others, optionally delete files, optionally add import-list exclusion)
- **History** — `GET /api/media/{id}/history` tab shows every edit

### `/media/stats` — Library statistics

Time-windowed counters (`?period=7d|30d|90d|all`). Shows additions, edits, duplicates resolved, low-rating / incomplete-metadata counts.

### `/media/labelarr` — Labelarr management

- Sync status per Plex library mapped in `labelarr.mappings`
- Per-item tag → label state
- Manual "Sync now" button queues a `labelarr` job

---

## Posters

### `/poster/search` (GDrive) and `/poster/assets` (local)

![Poster search](images/poster-search.png)

- GDrive search: loads all configured `sync_gdrive` sources on mount, filters across their indexes
- Local assets: browse what's already in `destination_dir`, filter by low-resolution / added-since / type

### `/poster/manage` — Per-poster view

- Preview at native size plus a thumbnail strip (`GET /api/posters/{id}/thumbnail`)
- **Download** dropdown supports size / format / quality overrides (`POST /api/posters/{id}/download`)
- **Optimize** button queues a `posters/optimize` run for just this poster

### `/poster/stats`

Total count, storage used, orphan count, duplicate count, low-resolution count. A "Backfill dimensions" action triggers `POST /api/posters/backfill-dimensions` incrementally.

---

## Settings

The sidebar's Settings section has eight children.

### `/settings/general`

`general.*` fields from `config.yml` — log level, update notifications, max logs, webhook delay/retries/secret, duplicate exclude groups.

### `/settings/interface`

Theme toggle (light / dark). Saves to `user_interface.theme` as the server default; the active session also persists to `localStorage` so your preference travels with you.

### `/settings/modules`

Sidebar nav for every registered module. Each page renders from the module's JSON schema (`GET /api/modules/{name}/schema`) and writes through `PUT /api/modules/{name}/config`.

Per-module pages include:
- A **Run now** button (queues a manual job)
- A **Test** button where applicable (connectivity test)
- Live run state indicator (SSE-driven)

### `/settings/schedule`

Cron/interval scheduler UI. Each module row shows current rule + next-run time. Saving writes `config.yml.schedule` and updates the scheduler in-process (no restart required).

### `/settings/instances`

Manage Radarr / Sonarr / Lidarr / Plex connections. Per-instance:
- Test connectivity (`POST /api/instances/{type}/{name}/test`)
- Inspect libraries / quality profiles / root folders / tags
- Enable / disable without deleting

Most-recent health probe per instance also shown — populated by the 6-hour system tick.

### `/settings/notifications`

Discord / Email / Apprise config per module. Supports template previews.

### `/settings/jobs`

Queue view. Filters: status, module, type. Per-row actions: retry, view log tail, open full log.

Bulk action: **Purge completed jobs older than N days** → `DELETE /api/jobs/old?days=30`.

### `/settings/webhooks`

- Generated webhook URLs for Sonarr / Radarr / Tautulli with the shared secret appended (or a copy-button that adds the header)
- "Recent origins" panel from `GET /api/jobs/webhook-origins?days=7`

---

## Logs

### `/logs`

Combined log viewer. Left rail lists modules; right panel tails the selected module's latest log. Controls:

- Level filter (debug / info / warn / error)
- Search in buffer
- Auto-scroll toggle
- Download full file

Log output is scrubbed by `SmartRedactionFilter` server-side — JWTs, Bearer tokens, `X-Api-Key`, `X-Plex-Token`, OAuth/webhook secrets, Discord webhook URLs, AWS keys, and GitHub tokens are replaced before they hit disk.

---

## Keyboard / URL conventions

- **Deep links** — every page is URL-addressable; state is serialised into query strings where useful (search terms, filters)
- **Filter persistence** — type / sort / order filters on media & poster search persist to `localStorage`
- **Theme** — toggle in the header; applies the `[data-theme]` attribute on `<html>`, driving all CSS variables
- **Responsive** — at <768px the sidebar collapses to a drawer, the dashboard quick-start row wraps, and the media / poster grids reduce to 1–2 columns

---

## Design tokens

CHUB's visual system is indigo-led, RoomSketch-inspired:

- **Primary**: `#463fbc` (light) / `#8767f7` (dark)
- **Surfaces**: floating rounded panel (`--radius-xl = 24px`) on a tinted background
- **Sidebar**: flush-left, deep indigo-black, small-caps section dividers
- **Dashboard accents**: 5 pastel badge palettes (rose / sky / lavender / peach / lime)
- **Typography**: Manrope (display) + Inter (body)
- **Shadows**: minimal — design leans on borders and surface contrast, not elevation

Full palette spec lives in `frontend/src/css/theme/{light,dark,tokens}.css`.

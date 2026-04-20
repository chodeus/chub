# CHUB Web UI Audit — Fix Plan & Progress

From full walks of the running UI at `192.168.2.206:8060`.
This file tracks what shipped, what's pending verification, and what's still open.

Legend: ✅ done / 🔄 verify after deploy / ⏳ not started

---

## Session recap — 2026-04-20

Thirteen commits landed between `6ae9165` and `755fad3`. Release-please cut **v1.1.0** (db53974) mid-session. Next deploy will jump the footer from `1.0.0.main53` to `1.1.0.mainN`.

Since v1.1.0 is a full minor bump, this PR plan supersedes all earlier entries — treat everything below as the new verification checklist.

### Shipped in v1.1.0 (headline items)

- Dashboard redesigned: Modules grid promoted to top with click-through to each module's logs, Recent jobs removed, new Scheduler full-width panel with computed "Up next" fire times, new Health section (disk dedup by device, instances enabled count, Last failure with module sub-text, orphan count, cached-poster count), Quick Start grew to 6 cards, footer pretty-prints version.
- Poster Cleanarr overhaul: ImageMaid parity confirmed (all modes + flags + safety rails), per-file `[MOVE]` / `[REMOVE]` / `[RESTORE]` audit logs, route renamed `/poster/manage` → `/poster/cleanarr` (old URL redirects), file renamed `PosterManagePage.jsx` → `PosterCleanarrPage.jsx`, scan no longer auto-fires on page load (explicit "Ready to scan" empty state → click Refresh), filter bar (Library / Media Type / Variant Kind) with media-type chips on bundle cards and kind chips on variant tiles.
- Assets Search: lightbox fixed (was fetching width=1200 from a 500-capped thumbnail endpoint → 422; now uses `getPreviewUrl` full-res), title wraps properly.
- Module settings: General renders at top on first paint (sorted static schema fallback).
- All settings pages: stopped hijacking Ctrl+R for form reset; browser reload works again.
- Breadcrumbs: canonical per-route chains (no more `Home / Assets / Search / Assets Search`), category labels non-clickable context.
- Browser tab title: per-route via `useDocumentTitle` hook.
- Jobs page: Duration column reads from `result.data.duration` seconds instead of using the future `scheduled_at`.
- Cross-module `instances` fields: `valueFormat: 'string'` on renameinatorr/nohl/health_checkarr/unmatched_assets.
- Backend: `FieldRegistry` circular-import race fixed (lazy resolver); `.chub_plex_db` moved off container root into `$CONFIG_DIR/plex-cache`; Cleanarr page surfaces 500s instead of pretending clean; `/api/system/disk` endpoint emits `device_id` + `shared_with` for dedup.
- Logs: `?tail=N` param added on GET `/api/logs/{module}/{filename}` (default 5000 from frontend), `/logs?module=…` query-param deep link.
- Empty-state improvements: RecentQueries chips on `/media/search` + `/poster/search/gdrive`.
- Header action-bar standardization on Library Manage / Library Search / Assets Search (actions moved into PageHeader `actions` slot).
- Media Statistics: red `0% MATCH` badge on By-Type / By-Instance rows where matched=0 but total>0.
- CI guardrails: `check-field-types.js` (settings_schema field types must exist in FieldRegistry); VERSION must match `.release-please-manifest.json` in Backend Lint step.
- Auth: verified `/api/system/disk` sits behind existing AuthMiddleware (returns 401 without Bearer).
- Run-now confirmation modal on Dashboard Modules.
- Requirements cleanup: dropped 5 confirmed-dead packages (`qbittorrent-api`, `Werkzeug`, `blinker`, `itsdangerous`, `dotenv` 0.9.9 alias). Started using `pathvalidate.sanitize_filename` for on-disk folder names at [plex.py:114](backend/util/plex.py:114). Kept for future optionality: `pathspec` (gitignore-style log filtering), `oauthlib` + `requests-oauthlib` (OAuth flows), `Markdown` + `Jinja2` + `MarkupSafe` (HTML email / CHANGELOG rendering), `prettytable` (log tables).
- release-please config: extra-files switched to `{type: generic, path: VERSION}` so VERSION auto-bumps on future releases.

---

## Next walk — verification checklist (tick through in order)

Once the image reaches `192.168.2.206:8060` (version should be ≥ `1.1.0.main60` or similar):

### Core data-correctness
1. **Dashboard Modules grid at top** — every tile clickable; click "Poster Renamerr" → `/logs?module=poster_renamerr` opens its log.
2. **Dashboard Recent jobs is gone** — nothing referencing "Recent jobs" visible.
3. **Dashboard Last failure card** — shows "Xh ago" + humanized module name; if no failures, shows "None · No failed jobs".
4. **Dashboard Run-now** on a Manual-only module opens a confirmation modal; Cancel does nothing; Run now queues.
5. **Dashboard Health** — at most one card per unique `device_id` (no three identical `/config`/`/kometa`/`/plex` cards); Instances card shows `N / N enabled`; cached + orphaned cards visible when counts > 0.
6. **Dashboard version footer** — reads `CHUB 1.1.0 · main #N` (not `1.0.4` and not `1.0.0`).

### Poster Cleanarr
7. `/poster/cleanarr` loads with **"Ready to scan"** empty state (no auto-scan).
8. Click **Refresh** → request to `/api/posters/plex-metadata/by-media` returns **200** (not 500).
9. After first scan: **Library + Type + Kind** filter row visible; Type/Kind dropdowns only list values present in the scan.
10. Bundle cards show **media-type chip** (movie/show/season/episode/collection); variant tiles show **kind chip** (poster/art/banner/thumb/etc).
11. `/poster/manage` (legacy URL) redirects to `/poster/cleanarr`.

### Assets Search
12. `/poster/search/assets` grid: ~7–8 tiles per row at desktop.
13. Click a tile → **lightbox opens with a non-broken image**; title wraps if long.
14. Lightbox **Download** button in footer opens the download-options modal.

### Settings
15. `/settings/jobs` **Duration column** shows values in seconds or sub-100 minutes for typical runs (not hundreds of minutes / hours).
16. `/settings/modules` **"General"** is the first module entry on first paint; doesn't reorder after schema load.
17. On `/settings/modules` (and `/general`, `/interface`): press **Ctrl+R** → browser reloads the page (not intercepted).
18. `/settings/instances` page-header icon renders (no blank circle).

### Breadcrumbs + titles
19. `/poster/search/assets` breadcrumb reads **Home / Assets / Assets Search** (not `… / Search / …`).
20. `Library` / `Assets` / `Settings` category crumbs are **plain text**, not links.
21. Browser tab title changes per route (e.g. `Dashboard · CHUB`, `Poster Cleanarr · CHUB`, `Sign in · CHUB`).

### Console + network (the prove-it bucket)
22. On every walked route (`/login`, `/dashboard`, `/media/*`, `/poster/*`, `/settings/*`, `/logs`): **zero console errors, zero warnings**. Specifically: the 14× `[FieldRegistry] Unknown field type: object_array` on `/settings/modules` should remain at zero.
23. Network panel per route: no 4xx / 5xx on normal navigation. (Verify `/api/posters/plex-metadata/by-media` 500 is gone and `/api/posters/229795/thumbnail?width=1200` 422 no longer happens from the lightbox.)
24. Log viewer: pick a module → request URL contains `?tail=5000`.

### Polish
25. Label badges render correctly: `0% MATCH` red badge on `/media/statistics` for Artist + Lidarr rows.
26. Empty-state chips: after doing a search on `/media/search`, navigate away and back → the prior query shows as a clickable chip.

---

## Still open (pick up when convenient)

### Needs a walk before finalizing (non-blocking for prod)
⏳ **Mobile viewport audit (<768px)**. Breadcrumb wrap, PageHeader action overflow, dashboard 6-card grid, Cleanarr filter row, lightbox sizing. Haven't exercised narrow screens yet.
⏳ **Light-mode visual pass.** Every session has been in dark mode.
⏳ **Poster Cleanarr end-to-end on real data.** With the `.chub_plex_db` path fix live, exercise the full report → move → restore → clear flow once.

### Medium-effort
⏳ **Thread `allowed_roots` into every remaining `MediaCache.delete()` caller.** Currently wired through `sync_for_instance` via the connector; other direct callers still use the legacy unscoped path. Low risk, worth a follow-up.
⏳ **Gitignore-style log filtering using `pathspec`.** Kept in requirements for this. Feature: let users set glob patterns in config to hide verbose log lines from the UI viewer.
⏳ **In-process OAuth flows using `oauthlib` / `requests-oauthlib`.** Kept for this. Feature: Trakt / Plex token refresh inside CHUB instead of shelling out to rclone for GDrive.
⏳ **Library Statistics chip rows → bar charts for skewed distributions.** Language (14), Rating (19), and similar high-cardinality sections render as identical-weight pills, so English 2209 looks the same size as Arabic 1 — you only notice the gap by reading numbers. Proposal: horizontal top-N bars for skewed high-cardinality stats (Language, Rating, Year, Genre), keep chips for small bounded sets (Status has 6 values), consider a donut for Monitored vs Unmonitored. Scope: separate PR, not part of the current mobile pass.
⏳ **Poster Cleanarr auto-select the lone Plex instance.** If only one Plex instance is globally configured AND the module's own `instances: []` is empty, the module should fall back to it instead of erroring out with "No Plex instances configured". Current UX gotcha: users configure one Plex instance globally (e.g. "Chodeus"), assume it covers the Cleanarr module too because the scan uses `plex_path` from disk, but Run Cleanup aborts in 0s because the per-module list is empty. File: [backend/modules/poster_cleanarr.py:250-256](backend/modules/poster_cleanarr.py:250).
⏳ **Lightbox image 403 on `/poster/search/assets`.** v1.1.0 fixed the thumbnail-cap 422 by switching the lightbox to `/api/posters/preview`, but `preview` rejects with `PATH_TRAVERSAL_DENIED` because the frontend sends `location=<owner_folder>` (e.g. "Solen01") while the backend expects `location` to be a configured allowed root (e.g. `/kometa`). Frontend call site: [frontend/src/pages/poster/PosterAssetsSearchPage.jsx:665](frontend/src/pages/poster/PosterAssetsSearchPage.jsx:665); backend guard: [backend/api/posters.py:1730](backend/api/posters.py:1730). Either adjust the frontend to split `item.file` into root+relative, or relax the preview endpoint to accept owner-folder→root resolution.

### Low-priority polish
⏳ **Library breadcrumb click target** — now that category labels aren't clickable, this is moot.
⏳ **Instance Health card** could become a live-status ping rather than configured-count. Currently counts enabled instances; live pings would mean N test calls per dashboard render. Design trade-off, not urgent.
⏳ **Frontend test suite.** CHUB has zero frontend tests; every regression so far has been caught by a manual walk, which is slow.
⏳ **Dashboard #18 version-string + build hash footer enhancement.** Current footer is cosmetic pretty-print; could embed a commit-hash link.
⏳ **`/logs` page breadcrumb** is intentionally skipped (top-level route). Revisit if nav feels uneven.

### Out of scope (by design)
- Per-module Discord config: CHUB centralizes via `/settings/notifications`.
- Per-module cron: CHUB centralizes via `/settings/schedule`.
- Artist/Lidarr 0% match root cause: data issue, not UI.
- Torrent cleanup (qbittorrent-api): dropped; outside CHUB's scope.

---

## Invocation cheatsheet for the next session

1. `cat WEBUI_AUDIT_PLAN.md` — start here.
2. `curl -sSf -m 5 http://192.168.2.206:8060/api/version` — verify base is `1.1.x` before walking.
3. Open Chrome MCP → `/dashboard` → read_console_messages + read_network_requests after each route.
4. Work through verification checklist 1-26 sequentially. Report pass/fail.
5. For any fail: grep the source, fix, verify prettier + lint + build + ruff, commit, push, watch CI (`gh run view <id>`), re-pull, re-verify.
6. When the list is green, close out `WEBUI_AUDIT_PLAN.md` with a one-line "v1.1.0 audit green" entry and open a new plan for whatever ships next.

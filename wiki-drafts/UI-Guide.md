# UI Guide

A page-by-page tour of CHUB's web interface. Open http://localhost:8000 and follow along.

## Dashboard

![Dashboard](images/dashboard-light.png)

The landing page at `/dashboard`. It's designed to answer three questions at a glance: *is anything running right now, what ran recently, and what's due to run next?*

At the top you'll see a friendly greeting, a live status dot (green when CHUB is receiving live updates, amber if it's polling), and a **New run** button that opens a picker for any module.

Below that there's a row of five pastel quick-start cards — Run module, Browse media, Browse posters, Find duplicates, and Inspect logs. Each one deep-links into the relevant page.

Under the cards, a **Recent jobs** strip shows the four most recent runs and whether they succeeded or failed. Click any card to open the full job log.

A **Scheduler callout** tells you which module is due to fire next and when. Finally, a **Module status grid** gives you one tile per installed module showing its current state (idle, running, queued, error).

## Media

### `/media/search` — Search & browse

![Media search](images/media-search.png)

One search box across every Radarr, Sonarr, and Lidarr you've configured. Filters on the right let you narrow by type (movie, series, album), sort, and order; your choice is remembered per browser. The recent-search dropdown under the box pulls from the last ten queries you ran on this device. Clicking any result opens its detail drawer.

### `/media/manage` — Details and editing

The full page for a single item. You can edit title, year, status, rating, studio, language, edition, and genre inline; every save records a row in the edit history so you can see what changed and when. A **Delete** button in the header opens a confirm dialog with an optional "also delete files from disk" checkbox.

If the item is part of a duplicate group, you'll see a resolution panel with a side-by-side picker — choose the copy to keep, optionally delete files from the others, and optionally add an import-list exclusion so CHUB doesn't re-download them.

A **History** tab shows every edit made to this item.

### `/media/statistics` — Library stats

Time-windowed counters: additions, edits, duplicates resolved, low-rating and incomplete-metadata counts. Pick a period with `?period=7d|30d|90d|all` in the URL or the selector on the page.

### `/media/labelarr` — Labelarr management

Shows the current sync state between your ARR tags and your Plex labels for every mapping configured in `labelarr.mappings`. There's a **Sync now** button that queues a labelarr job immediately rather than waiting for the schedule.

## Posters

### `/poster/search/gdrive` — GDrive search

Browse everything CHUB has indexed from your configured `sync_gdrive` sources. Filter across indexes by title, type, or path.

### `/poster/search/assets` — Local asset search

Browse what's already landed in your `destination_dir`. Filter by low-resolution, recently-added, or type.

### `/poster/manage` — Per-poster view

Preview at native size plus a thumbnail strip. Use the **Download** dropdown to grab the poster at a custom size, format, or quality. The **Optimize** button queues a one-off rewrite for just this poster.

### `/poster/statistics`

Total count, storage used, orphan count, duplicate count, and how many posters are below your resolution threshold. A **Backfill dimensions** button populates width/height for older posters so the low-resolution filter works on them.

## Settings

The Settings section of the sidebar has eight pages.

### `/settings/general`

The `general` block from `config.yml` — log level, update notifications, max log files, webhook delay and retries, webhook secret, and duplicate exclude groups. Saving writes the file back immediately.

### `/settings/interface`

Theme picker (light / dark). This sets the server-wide default; your current browser also remembers its own choice, so switching the theme in the header sticks on that device.

### `/settings/modules`

One page per module, with a sidebar nav. Each page is generated from the module's config schema, so every field is validated and documented. Per-module pages include:

- A **Run now** button to queue a manual job
- A **Test** button for modules that talk to external services (Plex / ARR / GDrive)
- A live run-state indicator

### `/settings/schedule`

Each scheduled module shows its current cron or interval rule plus the next-run time. Saving writes `config.yml.schedule` and updates the in-process scheduler — no restart required.

### `/settings/instances`

Manage your Radarr, Sonarr, Lidarr, and Plex connections. Per-instance controls: **Test** connectivity, view status, enable or disable without deleting. For Plex instances, the libraries list is fetched live so you can confirm CHUB sees what you expect. The most-recent health-probe result is shown per instance.

### `/settings/notifications`

Discord, Email, and Apprise configuration per module, plus an optional `main` entry for global notifications. A template preview shows what your Discord/Email will actually look like before you save.

### `/settings/jobs`

Queue view with filters for status, module, and type. Per-row actions: retry, view log tail, open full log. A bulk action purges completed jobs older than N days.

### `/settings/webhooks`

Generated webhook URLs for Sonarr / Radarr / Tautulli — if you set a webhook secret, the URLs have it pre-applied. A **Recent origins** panel shows which hosts and endpoints have fired webhooks in the last 7 days.

## Logs

### `/logs`

Combined log viewer. The left rail lists modules; the right panel tails the selected module's latest file. Controls include:

- Level filter (debug / info / warning / error)
- Search within the current buffer
- Auto-scroll toggle
- Download the full file

All output is scrubbed server-side: JWTs, Bearer tokens, API keys, Plex tokens, OAuth and webhook secrets, Discord webhook URLs, AWS keys, and GitHub tokens are replaced with placeholders before they hit disk.

## Conventions

**Deep links.** Every page is URL-addressable. Filters on media and poster search persist to your browser so they survive reloads and tab switches.

**Theme.** Toggle in the header; applies instantly, remembered per device.

**Responsive.** Below 768px the sidebar collapses to a drawer and grids reduce to one or two columns.

**Navigation shortcuts.** `/` redirects to `/dashboard`; `/media` redirects to `/media/search`; `/poster` redirects to `/poster/search/gdrive`. Unknown URLs bounce to the dashboard.

## Theme notes

CHUB's visual system is indigo-led and RoomSketch-inspired. The light theme leads with `#463fbc`; the dark theme shifts to `#8767f7`. Display type is Manrope, body type is Inter. The sidebar uses a deep indigo-black with small-caps section dividers. Dashboard accents use five pastel badge palettes (rose, sky, lavender, peach, lime).

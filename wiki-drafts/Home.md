<div align="center">

<img src="images/banner.png" alt="CHUB — Chodeus' Media Script Hub" width="520" />

[![MIT License](https://img.shields.io/badge/license-MIT-463fbc?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.8%2B-1992f3?style=flat-square)](https://www.python.org/)
[![Docker Image](https://img.shields.io/badge/ghcr.io-chodeus%2Fchub-463fbc?style=flat-square&logo=docker&logoColor=white)](https://github.com/chodeus/chub/pkgs/container/chub)

</div>

# CHUB — Chodeus' Media Script Hub

CHUB is a self-hosted web app that keeps a Plex library tidy. Point it at your Radarr, Sonarr, Lidarr, and Plex, and it takes care of the boring chores: renaming posters, finding duplicates, re-applying borders, searching for quality upgrades, cleaning up orphaned files, and more.

You run it in Docker, open it in a browser, configure it once, and then let it work on a schedule.

## Where to start

If you're installing for the first time, follow these three pages in order:

1. **[Installation](Installation)** — get CHUB running in Docker (10 minutes).
2. **[Configuration](Configuration)** — connect Radarr / Sonarr / Plex and pick the modules you want.
3. **[Modules](Modules)** — read the one-line summary for each module and decide which ones to turn on.

If CHUB is already running, jump to:

- **[UI Guide](UI-Guide)** — what every page in the app does.
- **[Webhooks](Webhooks)** — wire Sonarr/Radarr/Tautulli to trigger CHUB automatically.
- **[Troubleshooting](Troubleshooting)** — fixes for the things that usually go wrong.
- **[FAQ](FAQ)** — short answers to common questions.
- **[API](API)** — REST endpoints if you want to automate from scripts.
- **[Credits](Credits)** — DAPS lineage and third-party thanks.

## What CHUB does for you

**Keeps posters tidy.** Renames them to match your ARR/Plex naming, batch-optimizes file size, re-applies brand or holiday borders, pulls new ones from Google Drive, and cleans up orphans.

**Keeps media tidy.** Finds duplicates with fuzzy title matching, flags low-rated or incomplete items, lets you edit metadata inline with a full audit trail, and batch-imports into Radarr or Sonarr.

**Runs chores on a schedule.** Twelve built-in modules (upgrade searches, rename sweeps, health checks, hardlink audits, Google Drive sync, etc.) run on cron or interval — or on demand from the dashboard.

**Reacts to your ARR stack.** Webhooks from Sonarr/Radarr/Tautulli trigger poster rename and cleanup jobs the moment a new item lands, so you don't wait for the next scheduled run.

## What CHUB is not

- **Not a replacement for Kometa.** Kometa manages Plex metadata and collections; CHUB manages poster files and media chores. They complement each other.
- **Not for public internet exposure.** CHUB has built-in login, rate limiting, and SSRF protection, but no WAF or DDoS protection. Keep it on a LAN or behind a VPN / reverse proxy.
- **Not a DAPS upgrade.** CHUB is a fork of [DAPS](https://github.com/Drazzilb08/daps) with a refreshed UI and extra audit work. There's no data migration — it's a clean install. See [Credits](Credits).

## Screenshots

| Dashboard | Media | Posters |
| :---: | :---: | :---: |
| ![Dashboard](images/dashboard-light.png) | ![Media](images/media-search.png) | ![Posters](images/poster-manage.png) |

## Need help?

Open an issue at [chodeus/chub/issues](https://github.com/chodeus/chub/issues). Include the CHUB version (shown in Settings → Interface, or `GET /api/version`), your install method, and the relevant log excerpt.

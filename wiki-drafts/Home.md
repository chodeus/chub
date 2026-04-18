<div align="center">

<img src="images/banner.png" alt="CHUB — Chodeus' Media Script Hub" width="520" />

[![MIT License](https://img.shields.io/badge/license-MIT-463fbc?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.8%2B-1992f3?style=flat-square)](https://www.python.org/)
[![Docker Image](https://img.shields.io/badge/ghcr.io-chodeus%2Fchub-463fbc?style=flat-square&logo=docker&logoColor=white)](https://github.com/chodeus/chub/pkgs/container/chub)

</div>

# CHUB — Chodeus' Media Script Hub

A self-hosted, all-in-one media asset manager for your Plex/ARR stack. CHUB bundles a React UI, a FastAPI backend, and a set of scheduled modules that keep movie/TV libraries tidy.

---

## Quick links

- **[Installation](Installation)** — Docker Compose, CLI, bare-metal
- **[Configuration](Configuration)** — `config.yml` walkthrough
- **[Modules](Modules)** — what each module does
- **[API](API)** — REST endpoint reference
- **[UI Guide](UI-Guide)** — per-page tour
- **[Webhooks](Webhooks)** — wiring Sonarr/Radarr/Tautulli
- **[Troubleshooting](Troubleshooting)** — common issues
- **[FAQ](FAQ)** — setup and capability Q&A
- **[Credits](Credits)** — DAPS lineage + third-party thanks

---

## Feature matrix

| Area | Capability | Status |
|---|---|---|
| Posters | Rename, optimize, border-replace, cleanup, GDrive sync | ✅ |
| Posters | Low-resolution filter, thumbnail gen, on-the-fly resize/convert | ✅ |
| Media | Inline metadata edit with audit trail (`media_edit_history`) | ✅ |
| Media | Fuzzy duplicate detection + side-by-side resolution | ✅ |
| Media | Import movies/series into Radarr/Sonarr (batch + pre-lookup) | ✅ |
| Media | Time-windowed stats, low-rating, incomplete-metadata queries | ✅ |
| Media | Smart collections from media-cache tags | ✅ |
| Modules | 12 scheduled modules (see [Modules](Modules)) | ✅ |
| Modules | Cooperative cancellation via `threading.Event` | partial |
| Live | SSE channel at `/api/modules/events` (auto-reconnect) | ✅ |
| Live | Per-job cancel endpoint | ✅ |
| Live | Webhook ingest with optional HMAC shared secret | ✅ |
| System | 6-hour system-health tick with 30-day retention | ✅ |
| System | Activity digest + cleanup candidates endpoints | ✅ |
| Security | bcrypt + JWT auth, token-bucket login rate limiter | ✅ |
| Security | SSRF guard on outbound probes | ✅ |
| Security | Log redaction for JWT / API keys / OAuth secrets | ✅ |
| UI | Indigo-led light + dark themes, Manrope/Inter typography | ✅ |
| UI | Lidarr dedicated pages | ❌ *(music covered in upgradinatorr only)* |

Cancellation-unwired modules (tracked in `CLAUDE.md`): `poster_renamerr`, `labelarr`, `nestarr`, `renameinatorr`, `health_checkarr`, `border_replacerr`, `poster_cleanarr`.

---

## Screenshots

| Dashboard | Media | Posters |
| :---: | :---: | :---: |
| ![Dashboard](images/dashboard-light.png) | ![Media](images/media-search.png) | ![Posters](images/poster-manage.png) |

---

## Origin

CHUB is a fork of [DAPS](https://github.com/Drazzilb08/daps) by Drazzilb08, rebranded with a refreshed identity, indigo-led palette, and a dedicated audit pass that added SSE, cancellation, audit trails, and security hardening. Read [Credits](Credits) for the full acknowledgements.

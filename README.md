<div align="center">

<img src="assets/chub-logo.png" alt="CHUB logo" width="128" />

# ![CHUB](https://img.shields.io/badge/CHUB-463fbc?style=for-the-badge&labelColor=463fbc)

### Chodeus' Media Script Hub

A self-hosted, all-in-one media asset manager for your Plex/ARR stack.

[![MIT License](https://img.shields.io/badge/license-MIT-463fbc?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.8%2B-1992f3?style=flat-square)](https://www.python.org/)
[![Docker Image](https://img.shields.io/badge/ghcr.io-chodeus%2Fchub-463fbc?style=flat-square&logo=docker&logoColor=white)](https://github.com/chodeus/chub/pkgs/container/chub)
[![GitHub Issues](https://img.shields.io/github/issues/chodeus/chub?color=463fbc&style=flat-square)](https://github.com/chodeus/chub/issues)
[![GitHub Stars](https://img.shields.io/github/stars/chodeus/chub?color=53e8f0&style=flat-square)](https://github.com/chodeus/chub/stargazers)

</div>

---

## Screenshots

<!-- Fill in once dashboard screenshots are captured against the new theme. -->

| Light | Dark |
| :---: | :---: |
| ![Dashboard light](docs/images/dashboard-light.png) | ![Dashboard dark](docs/images/dashboard-dark.png) |

---

## What's included

CHUB bundles a React web UI, a FastAPI backend, and a set of scheduled modules that keep a Plex + Radarr/Sonarr/Lidarr library tidy.

**Library & metadata**
- Inline metadata editing with per-item audit history (`media_edit_history`)
- Duplicate detection with fuzzy title matching + side-by-side resolution UI
- Import movies/series into Radarr/Sonarr with pre-lookup validation
- Time-windowed stats, low-rating and incomplete-metadata queries
- Import-list exclusion inspection

**Posters**
- Batch optimization (resize, re-encode, WebP/JPEG conversion) via PIL
- Thumbnail generation and on-the-fly download processing (size/format/quality)
- Low-resolution filter, width/height indexing, `added-since` window query
- Smart collections generated from media-cache tags
- Orphaned-poster cleanup surfaced via `/api/system/cleanup-candidates`

**Modules (scheduled or on-demand)**
`poster_renamerr`, `poster_cleanarr`, `border_replacerr`, `labelarr`,
`jduparr`, `nohl`, `unmatched_assets`, `upgradinatorr`, `renameinatorr`,
`health_checkarr`, `nestarr`, `sync_gdrive`

**Live operation**
- SSE channel (`/api/modules/events`) for real-time module status
- Cooperative job cancellation (`DELETE /api/modules/{name}/execution/{job_id}`)
- Webhook ingest with optional shared-secret auth and origin tracking
- Built-in 6-hour system tick writing to `system_health_snapshots`

**Security posture**
- Token-bucket rate limiter on `/api/auth/login`
- SSRF guard on outbound instance probes (blocks cloud-metadata + reserved IPs)
- Argument-smuggling guards on path-valued config fields
- Log redaction for JWT, API keys, OAuth secrets, webhook URLs
- SQLite-backed auth with bcrypt password hashing

See [`docs/architecture.md`](docs/architecture.md) for the full picture.

---

## Quickstart

### Docker Compose (recommended)

```yaml
services:
  chub:
    image: ghcr.io/chodeus/chub:latest
    container_name: chub
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      PUID: "1000"
      PGID: "1000"
      TZ: "America/Los_Angeles"
    volumes:
      - /srv/apps/chub/config:/config
      - /srv/apps/chub/posters:/posters
      - /srv/media:/media
      - /srv/kometa/assets:/kometa:ro
```

```bash
docker compose up -d
```

Then open [http://localhost:8000](http://localhost:8000) and complete the first-run auth setup.

### Docker (single run)

```bash
docker run -d \
  --name chub \
  -p 8000:8000 \
  -v /srv/apps/chub/config:/config \
  -v /srv/apps/chub/posters:/posters \
  -v /srv/media:/media \
  ghcr.io/chodeus/chub:latest
```

### Local development

```bash
git clone https://github.com/chodeus/chub.git
cd chub

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py

# Frontend (separate terminal)
cd frontend
npm install
npm run dev       # Vite dev server on :5174, proxies /api to :8000
```

---

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Security](SECURITY.md)
- [GitHub Wiki](https://github.com/chodeus/chub/wiki) — installation, per-module reference, API, troubleshooting

---

## Contributing

PRs welcome for fixes, module ideas, and docs. Open an [issue](https://github.com/chodeus/chub/issues) first for anything larger than a patch so we can align on scope.

---

## Credits

CHUB builds on the original [DAPS](https://github.com/Drazzilb08/daps) project by **Drazzilb08** — thank you for the scripts and inspiration that made this fork possible.

Licensed under the [MIT License](LICENSE).

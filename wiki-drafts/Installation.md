# Installation

CHUB runs as a Docker container. The image is published at `ghcr.io/chodeus/chub:latest`.

This page covers three install paths. **Docker Compose is the recommended one** — if you're unsure, pick that.

## What you need

- A Linux host with Docker 24 or newer (or Docker Desktop on macOS/Windows).
- A folder on the host for CHUB's config, database, and logs (roughly 50–200 MB over time).
- Optional: the folders that already hold your posters, media, and Kometa assets (CHUB will read or write them).

Python 3.8+ and Node.js 20+ are only needed if you're doing a bare-metal install (see below).

## Option 1 — Docker Compose (recommended)

Create a folder for the stack, for example `/opt/stacks/chub/`, and save this as `compose.yaml` inside it:

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
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/api/health >/dev/null || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 45s
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp
```

Replace the four host paths on the left side of the volume mounts to match your setup. Set `PUID` / `PGID` to the user that owns those paths (on most Linux systems, `1000:1000`; on Unraid, `99:100`). Adjust `TZ` to your [timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

Start it:

```bash
docker compose up -d
```

Then open **http://localhost:8000** (or `http://<your-host>:8000` from another machine) and finish the first-run setup (see [First run](#first-run) below).

### Updating

```bash
docker compose pull
docker compose up -d
```

Upgrades don't require manual migrations — CHUB updates its database schema automatically on startup.

## Option 2 — Docker (single `docker run`)

If you don't use Compose:

```bash
docker run -d \
  --name chub \
  --restart unless-stopped \
  -p 8000:8000 \
  -e PUID=1000 -e PGID=1000 -e TZ=America/Los_Angeles \
  -v /srv/apps/chub/config:/config \
  -v /srv/apps/chub/posters:/posters \
  -v /srv/media:/media \
  -v /srv/kometa/assets:/kometa:ro \
  ghcr.io/chodeus/chub:latest
```

## Option 3 — Unraid

No Community Applications template yet. Add CHUB through Unraid's **Docker → Add Container** screen:

| Field | Value |
| --- | --- |
| Name | `chub` |
| Repository | `ghcr.io/chodeus/chub:latest` |
| Network Type | `bridge` |
| Port | `8000:8000` |
| Path `/config` | `/mnt/user/appdata/chub/` |
| Path `/posters` | your poster tree |
| Path `/media` | `/mnt/user/Media/` |
| Path `/kometa` | your Kometa asset folder (read-only) |
| Variable `PUID` | `99` |
| Variable `PGID` | `100` |
| Variable `UMASK` | `002` |
| Variable `TZ` | your timezone |

## Option 4 — Bare metal (development or Docker-free hosts)

Only pick this if you need to modify the code or Docker isn't available.

```bash
git clone https://github.com/chodeus/chub.git
cd chub

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Frontend (built into static files served by the backend)
cd frontend
npm install
npm run build
cd ..

# Run
export CONFIG_DIR="$(pwd)/config"
python3 main.py
```

Open http://localhost:8000.

For hot-reload development, run the frontend dev server in a second terminal:

```bash
cd frontend && npm run dev
# now open http://localhost:5174 — /api calls proxy to :8000
```

## First run

When CHUB is up:

1. Visit **http://localhost:8000**. You'll be prompted to create an admin user (minimum 8-character password).
2. Go to **Settings → Instances** and add your Radarr / Sonarr / Lidarr / Plex connections. Click **Test** on each to confirm CHUB can reach them.
3. Go to **Settings → General** to set the log level and — if you plan to expose webhook URLs beyond your LAN — a `webhook_secret`.
4. Go to **Settings → Modules**, pick a module you want to use, and fill in its config. See [Modules](Modules) for what each one does.
5. Go to **Settings → Schedule** and attach a cron or interval to modules you want to run automatically. Modules without a schedule stay manual-only.
6. Optional: **Settings → Notifications** for Discord / Email / Apprise; **Settings → Webhooks** for inbound Sonarr/Radarr/Tautulli hooks.
7. From the dashboard, click **New run** and trigger a module to confirm everything works before letting the scheduler take over.

## Resetting the admin password

There is no "forgot password" link in the UI. You have two ways to reset:

**From the command line (Docker):**

```bash
docker compose run --rm chub python3 main.py --reset-auth
```

Then restart CHUB and set up a new admin user on the first-run page.

**By editing config:** stop CHUB, open `config/config.yml`, delete the entire `auth:` block, and start CHUB again.

## Troubleshooting a failed install

If CHUB won't start, the container logs usually say why:

```bash
docker compose logs chub
```

Common issues and fixes are in [Troubleshooting](Troubleshooting).

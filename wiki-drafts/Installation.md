# Installation

CHUB ships as a prebuilt container image at `ghcr.io/chodeus/chub:latest`. Docker Compose is the recommended path; a single-run `docker run`, a bare-metal Python setup, and notes for Unraid follow.

---

## Prerequisites

- Docker 24+ (or Python 3.8+ and Node 20+ for bare metal)
- A writable config directory for `chub.db`, `config.yml`, and logs
- Optional: paths to existing poster + media libraries

---

## Docker Compose (recommended)

Drop this `compose.yaml` into `/opt/stacks/chub/`:

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
      DOCKER_ENV: "true"

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

Start and confirm it's up:

```bash
docker compose up -d
docker compose logs -f chub
curl http://localhost:8000/api/health
```

Open [http://localhost:8000](http://localhost:8000) and complete first-run auth setup (creates an admin user in `chub.db`).

### Updating

```bash
docker compose pull
docker compose up -d
```

---

## Docker CLI (single run)

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

---

## Bare-metal Python

Useful for development or hosts without Docker.

```bash
git clone https://github.com/chodeus/chub.git
cd chub

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Frontend build (served by FastAPI as static files)
cd frontend
npm install
npm run build
cd ..

# Run
export CONFIG_DIR=$(pwd)/config
python3 main.py
```

Visit [http://localhost:8000](http://localhost:8000).

### Dev mode (hot-reload frontend)

```bash
# Terminal 1 — backend
source .venv/bin/activate && python3 main.py

# Terminal 2 — frontend dev server (proxies /api to :8000)
cd frontend && npm run dev
# open http://localhost:5174
```

---

## Unraid

No official template yet. You can run CHUB via the stock `ghcr.io/chodeus/chub:latest` image using the Community Applications **Docker** tab:

1. **Name**: `chub`
2. **Repository**: `ghcr.io/chodeus/chub:latest`
3. **Network Type**: `bridge`
4. **Port**: `8000:8000` (host:container)
5. **Paths**:
   - `/config` → `/mnt/user/appdata/chub/`
   - `/posters` → wherever your poster tree lives
   - `/media` → `/mnt/user/Media/`
   - `/kometa` → your Kometa asset dir (read-only)
6. **Variables**: `PUID=99`, `PGID=100`, `UMASK=002`, `TZ=...`

A template XML will be published to `chodeus/chub` once the repo is live.

---

## First-run checklist

Once CHUB is up:

1. Register an admin user on the login page.
2. **Settings → Instances** — add your Radarr / Sonarr / Lidarr / Plex connections, test each.
3. **Settings → General** — set log level, max logs, webhook retry behavior, optional `webhook_secret`.
4. **Settings → Modules** — enable and configure the modules you want (see [Modules](Modules)).
5. **Settings → Schedule** — attach cron/interval schedules to the modules you want to run unattended.
6. **Settings → Notifications** — wire Discord / Email / Apprise if desired.
7. Trigger a manual run from the Dashboard (**New run** → pick a module) to confirm everything works before letting the scheduler take over.

See [Configuration](Configuration) for the `config.yml` schema.

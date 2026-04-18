# CHUB — Deployment Guide

CHUB ships as a prebuilt container image at `ghcr.io/chodeus/chub:latest`. You don't need to clone or build the repo to run it.

---

## Docker Compose (recommended)

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
      CONFIG_DIR: "/config"
      LOG_DIR: "/config/logs"
      HOST: "0.0.0.0"
      PORT: "8000"
      DOCKER_ENV: "true"

    volumes:
      - /srv/apps/chub/config:/config
      - /srv/apps/chub/posters:/posters
      - /srv/media:/media
      - /srv/kometa/assets:/kometa:ro
      - /etc/localtime:/etc/localtime:ro

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

```bash
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000). On first launch, CHUB prompts you to create an admin username and password.

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

## Recommended server layout

```
/opt/stacks/chub/
  compose.yaml          # your compose file
  .env                  # optional env overrides

/srv/apps/chub/
  config/               # config.yml, chub.db, logs/, backups/
  posters/              # poster files CHUB manages

/srv/media/
  movies/
  shows/

/srv/kometa/
  assets/               # Kometa poster assets (mount read-only)
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PUID` | `100` | User ID for file ownership inside the container |
| `PGID` | `99` | Group ID for file ownership |
| `UMASK` | `002` | File-creation umask |
| `TZ` | `America/Los_Angeles` | Container timezone |
| `CONFIG_DIR` | `/config` | Config + database directory |
| `LOG_DIR` | `/config/logs` | Log file directory |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Listen port |
| `DOCKER_ENV` | `false` | Set to `true` in containers; influences logging banner |
| `BRANCH` | `master` | Build metadata only |

---

## Volumes

| Mount | Purpose | Access |
|---|---|---|
| `/config` | `config.yml`, `chub.db`, `logs/`, `backups/` | read-write |
| `/posters` | Poster tree CHUB optimizes + renames | read-write |
| `/media` | Your media library (movies/shows) | read-write |
| `/kometa` | Kometa asset source | read-only typically |

---

## Health check

The container exposes `/api/health` and the compose file wires Docker's built-in healthcheck to it. Verify manually:

```bash
curl http://localhost:8000/api/health
```

The scheduler also runs a **system tick** every 6 hours that writes instance-reachability snapshots to the `system_health_snapshots` table — visible at `GET /api/system/health/snapshots` or the Settings → System page.

---

## Reverse proxy

CHUB has built-in authentication (username + password, bcrypt + JWT), so a reverse proxy is not strictly required. Still recommended for TLS termination and HTTP/2.

### Caddy

```caddyfile
chub.example.com {
    reverse_proxy localhost:8000
}
```

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name chub.example.com;

    # TLS config omitted — use certbot or your existing setup

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host               $host;
        proxy_set_header   X-Real-IP          $remote_addr;
        proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto  $scheme;

        # SSE support — disable buffering, extend read timeout
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 1h;
    }
}
```

### Traefik (labels on the Compose service)

```yaml
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.chub.rule=Host(`chub.example.com`)"
      - "traefik.http.routers.chub.entrypoints=websecure"
      - "traefik.http.routers.chub.tls.certresolver=letsencrypt"
      - "traefik.http.services.chub.loadbalancer.server.port=8000"
```

**Important for SSE**: any proxy you use needs buffering disabled for `/api/modules/events`. Caddy handles this automatically; Nginx needs `proxy_buffering off` as shown.

---

## Backup & restore

CHUB exposes backup endpoints over the API:

- `POST /api/system/backup` — creates a zip of `config.yml` + `chub.db` and returns it as a download.
- `GET /api/system/backups` — lists existing backups.
- `POST /api/system/restore` — upload a backup zip to restore config + DB.

Backups are also written to `$CONFIG_DIR/backups/` on the host.

### Manual backup

If you prefer filesystem-level snapshots:

```bash
# Stop the container first to ensure SQLite consistency
docker compose stop chub

tar czf chub-backup-$(date +%F).tar.gz -C /srv/apps/chub config

docker compose start chub
```

To restore, stop the container, replace `/srv/apps/chub/config`, and start it back up.

---

## Troubleshooting

- **Permission errors on `/config` or `/posters`** — check `PUID`/`PGID` match the host user that owns the bind-mount directories.
- **SSE disconnects immediately behind a proxy** — verify `proxy_buffering off` (Nginx) or equivalent is set for `/api/modules/events`.
- **Login returns 429** — token-bucket rate limiter kicked in. Default is 1 request per 5 s with a burst of 5. Wait a few seconds and retry.
- **Instance health probe fails with SSRF error** — the SSRF guard blocks cloud-metadata IPs (`169.254.169.254`, `metadata.google.internal`) and reserved ranges. If your Radarr/Sonarr lives on one of these, expose it on a routable IP.
- **Full reset** — stop the container, delete the config directory, start it back up. CHUB will re-initialise `chub.db` and walk you through first-run auth again.

See the [Troubleshooting wiki page](https://github.com/chodeus/chub/wiki/Troubleshooting) for more.

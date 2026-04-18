# Troubleshooting

Common issues and how to diagnose them. For anything not covered here, check module logs at **Logs** in the UI or `$LOG_DIR/*.log` on disk, then open an issue on [chodeus/chub](https://github.com/chodeus/chub/issues) with the relevant excerpt.

---

## Container / startup

### Container won't start

```bash
docker compose logs chub
```

Look for one of:

- **`Configuration file not found: /config/config.yml`** — first-run case; delete the container, make sure the config directory is writable, start again. CHUB will create a default config.
- **`Configuration validation failed`** — CHUB prints each offending field + message. Fix `config.yml` or remove the bad section and restart.
- **`Address already in use`** — another process holds port 8000. Either stop it or change `ports:` in compose.
- **Permission denied on `/config`** — `PUID`/`PGID` don't match the bind-mount owner. `chown -R <puid>:<pgid> /srv/apps/chub/config`.

### Health check keeps failing

```bash
curl http://localhost:8000/api/health
```

If this works locally but Docker's healthcheck fails, the issue is usually networking on the container — check `docker inspect chub` and verify the port binding. A `healthcheck` timeout can also happen on slow first-launch DB init; raise `start_period` to 90s.

### First-run auth page doesn't appear

Hit `GET /api/auth/status`. If it returns `{ "configured": true }` but you can't log in, your `auth` section is present but you don't know the credentials. Fix by stopping CHUB, deleting the `auth:` block from `config.yml`, and restarting — the first-run form will reappear.

---

## Auth

### Login returns 429

Token-bucket rate limiter (1 req / 5 s, burst 5). Wait a few seconds and retry. If you're getting this legitimately during normal use, you're probably hitting `/api/auth/login` programmatically — use the JWT from a single login instead.

### JWT expired mid-session

Frontend auto-redirects to the login page on a `401`. If you're scripting against the API, re-hit `POST /api/auth/login` to get a fresh token (expiry defaults to 24 hours, configurable via `auth.token_expiry_hours`).

### "Forgot" admin password

There is no password-reset flow. Stop CHUB, edit `config.yml`, remove the `auth:` block, restart — you'll get the first-run form.

---

## Instances (Radarr / Sonarr / Lidarr / Plex)

### Instance test fails

From **Settings → Instances**, click **Test** on the failing instance. Common causes:

- **Connection refused** — URL or port wrong; CHUB is hitting `http://radarr:7878` but the container name is different.
- **Timeout** — ARR not running, or firewall between CHUB and the service. Confirm with `curl -sS <url>/api/v3/system/status -H 'X-Api-Key: <key>'` from inside the CHUB container: `docker compose exec chub curl ...`.
- **403 / 401** — wrong API key. Copy it fresh from the ARR's **Settings → General → Security**.
- **SSRF-blocked** — URL resolves to a reserved / cloud-metadata range. Use a routable IP or hostname.

### Plex returns 401

`api` field should be the `X-Plex-Token`, not a login. Get it from [Finding a Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

### Instance probe shows "healthy" but a module run fails

The 6-hour system tick only confirms connectivity, not the specific endpoints a module uses. Check the module's run log — it'll show the exact endpoint + status code that failed.

---

## SSE / live updates

### Dashboard doesn't update in real time

The browser is polling, not receiving SSE. Check the Network panel for a request to `/api/modules/events` — it should stay open with `Content-Type: text/event-stream`. Common reasons it closes:

- **Reverse proxy buffering** — Nginx's default is to buffer responses. Add `proxy_buffering off;` for the `/api/modules/events` location (see [Deployment → Reverse proxy](../docs/deployment.md#reverse-proxy)).
- **Auth** — EventSource can't send custom headers, so it falls back to `?token=<jwt>`. If the token expired, the stream gets `401` and disconnects.
- **Gzip** — some proxies compress SSE, which breaks streaming. Disable for the events endpoint.

The frontend hook retries with exponential backoff; if it never succeeds, the UI silently falls back to polling `/api/modules/run-states` every few seconds.

### SSE works but job cancellation does nothing

Not every module checks `is_cancelled()` yet. These modules do:
- `upgradinatorr`
- `jduparr`
- `nohl`
- `sync_gdrive`
- `unmatched_assets`

These don't:
- `poster_renamerr`, `labelarr`, `nestarr`, `renameinatorr`, `health_checkarr`, `border_replacerr`, `poster_cleanarr`

For non-cancellable modules, you can stop the job by restarting the container, but that's disruptive. Cancellation for the remaining modules is on the roadmap.

---

## Modules

### `poster_renamerr` runs but nothing moves

Likely causes:

- `dry_run: true` — check the module config.
- `source_dirs` empty or wrong — nothing to rename.
- `destination_dir` not writable by the PUID/PGID.
- No matching ARR items — enable `debug` log level and re-run; you'll see per-item match attempts.
- `action_type: hardlink` across filesystems — hardlinks can't cross volumes; switch to `copy` or move both paths to the same volume.

### `jduparr` runs forever

It's hashing your whole library. On large trees this takes hours the first time. Enable `hash_database` (path) so subsequent runs are incremental. Cancel via `DELETE /api/modules/jduparr/execution/{job_id}` — it will stop on the next file boundary.

### `sync_gdrive` fails with "invalid path"

The `path_safety` guard rejects `hash_database`, `sync_location`, `gdrive_sa_location`, and folder IDs if they contain null bytes or start with `-`. Rewrite the value so it doesn't.

### `poster_cleanarr` does nothing

- `mode: report` — dry-run only. Switch to `mode: clean` to actually delete.
- `plex_path` wrong — this must be the Plex metadata directory visible to the CHUB container, not a URL.

---

## Posters

### Thumbnails are slow on first view

`GET /api/posters/{id}/thumbnail` generates and caches the thumbnail on demand. First hit for each poster is slow; subsequent hits are fast. Pre-warm by triggering `POST /api/posters/backfill-dimensions` + a view of the posters page.

### Low-resolution filter returns nothing

You need to run `POST /api/posters/backfill-dimensions` first — the `width` / `height` columns aren't populated until you do.

---

## Database

### `chub.db is locked`

SQLite allows one writer. Usually surfaces during concurrent cancel + queue operations. Usually harmless — CHUB retries. If it persists, check for another process holding a handle (`fuser` or `lsof`) — typically a backup script or another container.

### Database is huge

Run the retention endpoints:

```
DELETE /api/jobs/old?days=30
```

The scheduler also auto-prunes `system_health_snapshots` older than 30 days on every 6-hour tick.

---

## Webhooks

### Webhooks return `401`

`general.webhook_secret` is set but the caller isn't sending `X-Webhook-Secret` or `?secret=`. Copy the generated URL from **Settings → Webhooks** — it bakes the secret in.

### Sonarr says "Test connection failed" to CHUB

Sonarr's test fires a specific `Test` event type; CHUB accepts it and returns `200`. If Sonarr reports failure, it's almost always a network issue: Sonarr can't reach the CHUB host/port. Verify with:

```bash
docker compose exec sonarr curl -I http://chub:8000/api/health
```

---

## Logs

### Log files fill the disk

Lower `general.max_logs` (default 9 → rotated files per module). Old rotations are deleted automatically on write.

### Log redaction ate a value I actually needed

`SmartRedactionFilter` only redacts known-secret patterns (JWTs, Bearer tokens, `X-Api-Key`, `X-Plex-Token`, OAuth secrets, webhook URLs, AWS/GitHub tokens). If it redacted something it shouldn't have, file an issue with the offending pattern — false positives should be rare.

---

## Still stuck?

1. Enable `debug` log level on the misbehaving module and reproduce.
2. Grab the relevant log excerpt (redacted is fine — CHUB already scrubs secrets).
3. Open an issue: [chodeus/chub/issues](https://github.com/chodeus/chub/issues) with:
   - What you expected
   - What happened instead
   - CHUB version (`GET /api/system/version`)
   - Container or bare-metal
   - Log excerpt

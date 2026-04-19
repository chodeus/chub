# Troubleshooting

Common problems and how to diagnose them. For anything not covered here, open the module's log from **Logs** in the UI, or open an issue at [chodeus/chub/issues](https://github.com/chodeus/chub/issues) with the relevant excerpt.

## Container / startup

### Container won't start

```bash
docker compose logs chub
```

Look for one of these:

**`Configuration file not found: /config/config.yml`** — first-run case. Delete the container, make sure the `/config` bind-mount exists and is writable, start again. CHUB will create a default config.

**`Configuration validation failed`** — CHUB prints which field failed. Fix `config.yml` or remove the bad section and restart — missing sections fall back to defaults.

**`Address already in use`** — another process is holding port 8000. Either stop it or change the `ports:` line in your compose file.

**Permission denied on `/config`** — `PUID`/`PGID` don't match the owner of the bind-mount directory. Run `chown -R <puid>:<pgid> /srv/apps/chub/config` on the host.

### Health check keeps failing

From inside the host:

```bash
curl http://localhost:8000/api/health
```

If that works but Docker's healthcheck fails, it's networking on the container — check `docker inspect chub` and confirm the port binding. A healthcheck timeout can also happen on slow first-launch DB init; raise `start_period` in your compose file to 90s.

### First-run auth page doesn't appear

Hit `GET /api/auth/status`. If it returns `{ "configured": true }` but you don't know the credentials, see [Resetting the admin password](#forgot-admin-password) below.

## Auth

### Login returns `429`

The login rate limiter fired. Wait 5–10 seconds and retry. If you're hitting it during normal use, you're probably calling `POST /api/auth/login` in a script on every request — re-use one token (the default expiry is 24 hours; bump `auth.token_expiry_hours` for automation).

### JWT expired mid-session

The frontend auto-redirects to the login page on `401`. For scripting, just call `POST /api/auth/login` again to get a fresh token.

### Forgot admin password

Two fixes:

**From the command line (Docker Compose):**

```bash
docker compose run --rm chub python3 main.py --reset-auth
```

Then restart CHUB — the first-run form will reappear.

**By editing config:** stop CHUB, open `config/config.yml`, delete the entire `auth:` block, start CHUB again.

## Instances (Radarr / Sonarr / Lidarr / Plex)

### Instance test fails

From **Settings → Instances**, click **Test** on the failing instance. Common causes:

- **Connection refused** — URL or port wrong. `http://radarr:7878` only works if both containers are on the same Docker network.
- **Timeout** — the ARR isn't running or there's a firewall between them. Confirm from inside the CHUB container: `docker compose exec chub curl -sS <url>/api/v3/system/status -H 'X-Api-Key: <key>'`.
- **403 / 401** — wrong API key. Copy it fresh from the ARR's **Settings → General → Security**.
- **SSRF-blocked** — your URL resolves to a reserved / cloud-metadata / link-local IP range. Use a routable IP or hostname.

### Plex returns 401

The `api` field for a Plex instance is the `X-Plex-Token`, not a Plex login. See [Finding a Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

### Instance probe shows "healthy" but a module run fails

The 6-hour health probe only confirms basic connectivity, not the specific endpoints a module uses. Check the module's run log — it'll show the exact endpoint and status code that failed.

## Live updates / cancellation

### Dashboard doesn't update in real time

The browser should be receiving server-sent events from `/api/modules/events`. If it's not, it silently falls back to polling. Common causes:

- **Reverse proxy buffering** — Nginx buffers responses by default; that breaks SSE. Add `proxy_buffering off;` for the `/api/modules/events` location.
- **Auth expired mid-stream** — `EventSource` can't refresh tokens, so an expired JWT disconnects the stream. Refresh the page.
- **Gzip on SSE** — some proxies compress event streams, which breaks framing. Disable compression for that endpoint.

### Cancel button doesn't stop `border_replacerr`

Cancellation is cooperative: a module has to check a cancel flag in its loop. Eleven of the twelve modules (`poster_renamerr`, `poster_cleanarr`, `labelarr`, `jduparr`, `nohl`, `unmatched_assets`, `upgradinatorr`, `renameinatorr`, `health_checkarr`, `nestarr`, `sync_gdrive`) stop on the next iteration.

`border_replacerr` does **not** check the flag yet — it runs to completion. To interrupt one in progress you have to restart the container. Cancellation for `border_replacerr` is on the roadmap.

## Modules

### `poster_renamerr` runs but nothing moves

Likely causes:

- `dry_run: true` in the module config.
- `source_dirs` empty or wrong.
- `destination_dir` isn't writable by `PUID`/`PGID`.
- No matching ARR items — enable `debug` log level and re-run; the log shows per-item match attempts.
- `action_type: hardlink` and source/destination are on different filesystems (hardlinks can't cross volumes). Switch to `copy` or move both paths to the same volume.

### `jduparr` runs forever

It's hashing your whole library. On a large tree the first run takes hours. Subsequent runs are incremental because CHUB persists hashes to `hash_database`. To cancel: **Settings → Jobs → Cancel** (or `DELETE /api/modules/jduparr/execution/{job_id}`) — it will stop at the next file boundary.

### `sync_gdrive` fails with "invalid path"

The path-safety guard rejects `hash_database`, `sync_location`, `gdrive_sa_location`, and folder IDs that contain null bytes or start with `-`. Rewrite the value so it doesn't.

### `poster_cleanarr` does nothing

Check the mode. The module supports these values:

- `report` — dry-run; lists orphans without touching anything.
- `move` — relocates orphans to a `Poster Cleanarr Restore` folder.
- `remove` — deletes orphans outright.
- `restore` — moves anything in the restore folder back where it came from.
- `clear` — deletes the restore folder.
- `nothing` — skips image work but still runs `empty_trash` / `clean_bundles` / `optimize_db` if those flags are on.

If you're in `report` you'll see a list but no changes — that's by design. Switch to `move` first (easy to undo with `restore`) then `remove` once you trust it.

Also check that `plex_path` is a filesystem path to the Plex `Metadata/` directory as visible from inside the CHUB container — not a URL.

## Posters

### Thumbnails are slow on first view

`GET /api/posters/{id}/thumbnail` generates and caches a JPEG thumbnail on demand. The first hit is slow; subsequent hits are fast. To pre-warm a whole library, trigger `POST /api/posters/backfill-dimensions` and then open the posters page.

### Low-resolution filter returns nothing

It needs `width` / `height` on each poster. Run `POST /api/posters/backfill-dimensions` (or click **Backfill dimensions** on the poster stats page) once and it'll populate the columns.

## Database

### `chub.db is locked`

SQLite allows exactly one writer. You'll see this briefly during concurrent cancel / queue operations; CHUB retries automatically. If it persists, something else is holding a handle — typically a backup script or another container mounting the DB file.

### Database is huge

Run the retention endpoint:

```
DELETE /api/jobs/old?days=30
```

The scheduler also auto-prunes `system_health_snapshots` older than 30 days on every 6-hour tick.

## Webhooks

### Webhooks return `401`

`general.webhook_secret` is set but the caller isn't sending `X-Webhook-Secret` or `?secret=`. Copy the generated URL from **Settings → Webhooks** — it applies the secret for you.

### Sonarr says "Test connection failed"

Almost always a network issue: Sonarr can't reach CHUB. Verify from inside Sonarr's container:

```bash
docker compose exec sonarr curl -I http://chub:8000/api/health
```

## Logs

### Log files fill the disk

Lower `general.max_logs` (default 9 rotated files per module). Old rotations are deleted automatically on the next write.

### Log redaction ate a value I actually needed

The redaction filter only replaces known secret patterns (JWTs, Bearer tokens, API keys, Plex tokens, OAuth/webhook secrets, Discord webhook URLs, AWS keys, GitHub tokens). False positives should be rare — if it redacted something it shouldn't have, file an issue with the offending pattern.

## Still stuck?

1. Switch the misbehaving module to `log_level: debug` and reproduce.
2. Grab the log excerpt (redacted is fine — CHUB scrubs secrets before writing).
3. Open an issue at [chodeus/chub/issues](https://github.com/chodeus/chub/issues) with:
   - What you expected to happen
   - What happened instead
   - CHUB version (`GET /api/version` or the footer of the Settings page)
   - Container or bare-metal install
   - The log excerpt

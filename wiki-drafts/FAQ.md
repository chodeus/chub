# FAQ

Short answers to the most common questions. For anything not here, see [Troubleshooting](Troubleshooting).

### What is CHUB?

A self-hosted web app that keeps a Plex library tidy. Point it at Radarr, Sonarr, Lidarr, and Plex and it handles the boring chores: renaming posters, finding duplicates, re-applying borders, searching for quality upgrades, cleaning up orphaned files, and more. See [Home](Home).

### How is it different from DAPS?

Same module set, different direction. CHUB is a fork of [DAPS](https://github.com/Drazzilb08/daps) with a refreshed UI, cooperative cancellation on 11 of the 12 modules, live updates via server-sent events, inline metadata editing with an audit trail, duplicate resolution, 6-hour system-health snapshots, token-bucket login rate limiter, SSRF guard, and expanded log redaction. See [Credits](Credits) for the full list.

### Can I migrate my DAPS install to CHUB?

No. CHUB is a clean break — no data migration, no compatibility shims. Pull `ghcr.io/chodeus/chub:latest` into a fresh config directory and reconfigure. Your DAPS install keeps working on its own image alongside CHUB if you want to run both side-by-side during cut-over.

### Is CHUB safe to expose on the public internet?

**Not directly.** CHUB is built for a private network — LAN or VPN. It has built-in auth (bcrypt + JWT), a login rate limiter, and SSRF protection, but no WAF, IP allow-list, or DDoS mitigation. For remote access, put it behind a reverse proxy with TLS plus a second auth layer (Authelia, Authentik, Cloudflare Access, etc.).

### How do I reset the admin password?

Two options:

Run the reset command and restart CHUB:

```bash
docker compose run --rm chub python3 main.py --reset-auth
```

Or stop CHUB, delete the `auth:` block from `config.yml`, and start CHUB again. Either way the first-run form reappears.

### Does CHUB work with a 4K-split Plex library?

Yes. Use `nestarr` to move items between split libraries based on ARR path mappings, and configure each Plex library separately under `instances.plex`. `poster_renamerr` also accepts a `library_names` list so you can scope each Plex instance.

### Does CHUB support Lidarr?

Yes for `upgradinatorr` — full album search, artist grouping, and all three search modes (`upgrade`, `missing`, `cutoff`). There's no dedicated Lidarr UI because music library browsing is covered by Lidarr itself. Open an issue if you'd like a Lidarr-specific workflow built into CHUB.

### How do I run a module right now instead of waiting for the schedule?

From the UI: **Dashboard → New run**, pick the module, **Run**.

From the API: `POST /api/modules/{name}/execute`.

### How do I stop a running module?

From the UI: **Settings → Jobs → click the running job → Cancel**.

From the API: `DELETE /api/modules/{name}/execution/{job_id}`.

Cancellation is cooperative — the module has to check a cancel flag in its loop. 11 of the 12 modules do: `poster_renamerr`, `poster_cleanarr`, `labelarr`, `jduparr`, `nohl`, `unmatched_assets`, `upgradinatorr`, `renameinatorr`, `health_checkarr`, `nestarr`, `sync_gdrive`. `border_replacerr` doesn't yet — if you start a big run you have to restart the container to stop it.

### Where does CHUB keep its data?

Everything under `${CONFIG_DIR}` (default `/config` inside the container):

- `config.yml` — YAML config
- `chub.db` — SQLite database (users, jobs, media cache, edit history, health snapshots, poster cache)
- `logs/` — per-module log files
- `backups/` — zips from `POST /api/backup`

Your poster and media trees live on the volumes you mount separately.

### How do I back it up?

Two options:

1. From the UI (or API): `POST /api/backup` returns a zip of `config.yml` + `chub.db`. It's also written to `$CONFIG_DIR/backups/`.
2. Filesystem: stop the container (for SQLite consistency), `tar` the config directory, restart.

### How do I update?

```bash
docker compose pull
docker compose up -d
```

Schema changes are applied automatically on startup — no manual migrations.

### Can I use CHUB with just one ARR instance?

Yes. Multi-instance support is optional — configure only the instances you actually run.

### Does CHUB have an API key for integrations?

No dedicated API-key system. Use the JWT from `POST /api/auth/login` as a bearer token; bump `auth.token_expiry_hours` if you need long-lived automation. For inbound webhooks, use `general.webhook_secret` instead.

### Do I need both Kometa and CHUB?

No. They solve different problems — Kometa manages Plex metadata and collections, CHUB manages poster file trees and media-asset chores. Many people run both. `poster_renamerr` is explicitly designed to consume Kometa's asset output.

### Can I disable modules I don't use?

Yes. Just don't configure them and don't schedule them. Every module has a sidebar entry, but an unconfigured module simply won't do anything when triggered.

### What's the container user / permissions model?

The image runs as `dockeruser`, with UID/GID set via `PUID`/`PGID` env vars. The defaults are `100` / `99` (matching Unraid). Most other Linux hosts want `1000` / `1000`. Mount paths must be writable by whichever UID/GID you pick.

### How do I contribute?

1. Open an issue first for anything non-trivial.
2. Fork, branch, PR against `main`.
3. Run linters (`ruff` for Python, `eslint` for JS) and build the frontend (`npm run build`) before pushing.
4. Keep PRs focused — one feature per PR.

Small fixes can skip the issue step.

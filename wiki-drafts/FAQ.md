# FAQ

Short answers to the most common questions. For anything not here, see [Troubleshooting](Troubleshooting) or open an issue.

---

### What is CHUB?

A self-hosted media-asset manager for a Plex + Radarr/Sonarr/Lidarr stack. It bundles a React web UI and a FastAPI backend that orchestrates scheduled modules against your libraries, poster trees, and cloud drives. See [Home](Home).

---

### How is it different from DAPS?

Same module set, different direction. CHUB is a fork of [DAPS](https://github.com/Drazzilb08/daps) with a rebranded identity (indigo-led UI redesign, new logos, Manrope/Inter typography) and a dedicated audit pass that added SSE, cancellation, audit trails, security hardening, activity digests, and batch operations. See [Credits](Credits) for the full list of what CHUB adds on top of DAPS.

---

### Can I migrate my DAPS install to CHUB?

No. CHUB is a clean break — no data migration, no git history carried over, no compatibility shims. Pull the `ghcr.io/chodeus/chub:latest` image into a fresh config directory and reconfigure from scratch. Your DAPS install keeps working on its own image.

---

### Is CHUB safe to expose on the public internet?

**Not directly.** CHUB is built for a private network — a LAN or a VPN. It has built-in auth (bcrypt + JWT), a login rate limiter, and SSRF protection, but no WAF, IP allowlist, or DDoS mitigation. If you need remote access, put it behind a reverse proxy with TLS and ideally a second layer of auth (Authelia, Authentik, etc.). See [SECURITY](../SECURITY.md).

---

### How do I reset the admin password?

Stop CHUB, delete the `auth:` block from `config.yml`, restart. First-run form reappears. There is no self-service password reset from the UI — this is intentional for a single-user app.

---

### Does CHUB work with a 4K-split Plex library?

Yes. Use `nestarr` for moving items between split libraries based on ARR path mappings, and configure your Plex libraries separately in `instances.plex`. The `poster_renamerr` module also accepts a `library_names` scoping list per Plex instance.

---

### Does CHUB support Lidarr?

Partially. `upgradinatorr` has full Lidarr support (album search, artist grouping, wanted / missing / cutoff modes). There are no dedicated Lidarr UI pages — music library browsing / editing is covered by Lidarr itself. If you want a Lidarr-specific workflow built into CHUB, open an issue describing what you'd want to see.

---

### How do I run a module right now instead of waiting for the schedule?

From the UI: **Dashboard → New run**, pick the module, optionally override any one-shot knobs, **Run**.

From the API: `POST /api/modules/{name}/execute`.

---

### How do I stop a running module?

From the UI: Settings → Jobs → click the running job → **Cancel**.

From the API: `DELETE /api/modules/{name}/execution/{job_id}`.

Cancellation is cooperative — modules have to check `is_cancelled()` in their loop. Currently wired: `upgradinatorr`, `jduparr`, `nohl`, `sync_gdrive`, `unmatched_assets`. Others will hang until their current step finishes; restart the container if you need to stop them immediately.

---

### Where does CHUB keep its data?

Everything lives in `${CONFIG_DIR}` (default `/config` in Docker):

- `config.yml` — YAML config
- `chub.db` — SQLite database (users, jobs, media cache, edit history, health snapshots, poster cache)
- `logs/` — per-module log files
- `backups/` — zips from `POST /api/system/backup`

Poster and media trees live on the volumes you mount separately.

---

### How do I back it up?

Two options:

1. **API:** `POST /api/system/backup` returns a zip of `config.yml` + `chub.db`. Also written to `$CONFIG_DIR/backups/`.
2. **Filesystem:** stop the container (for SQLite consistency), tar the config directory, restart. See [Deployment → Backup](../docs/deployment.md#backup--restore).

---

### How do I update?

```bash
docker compose pull
docker compose up -d
```

Schema changes are additive — CHUB runs `add_missing_columns` on startup so upgrades don't require migrations.

---

### Can I use CHUB with a single ARR instance?

Yes. Multi-instance support is optional — configure only the instances you actually run.

---

### Does CHUB have an API key for integrations?

No dedicated API-key system. Use the JWT from `POST /api/auth/login` as a long-lived token; set `auth.token_expiry_hours` in `config.yml` to something long-lived for automation. For webhooks, use `general.webhook_secret` instead.

---

### Do I need both Kometa and CHUB?

No. They solve different problems — Kometa manages Plex metadata/collections, CHUB manages poster file trees + media asset chores. Many users run both. `poster_renamerr` is specifically designed to consume Kometa's asset output.

---

### Can I disable modules I don't use?

Yes — just don't configure them and don't schedule them. Module pages in the UI always render (the sidebar has one per module), but an unconfigured module simply won't do anything when triggered.

---

### What's the container user / permissions model?

The image runs as `dockeruser` (UID/GID set via `PUID`/`PGID` env vars, defaults `100` / `99`). Mount paths must be writable by that UID — Unraid's defaults (`99:100`) match; most Linux setups want `1000:1000`.

---

### How do I contribute?

1. Open an issue first for anything non-trivial — alignment on scope saves rework.
2. Fork, branch, PR against `main`.
3. Run the linters (`ruff` for Python, `eslint` for JS) + build the frontend (`npm run build`) before pushing.
4. Keep PRs focused; one feature per PR.

Patch-level fixes can skip the issue step.

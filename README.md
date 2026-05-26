<div align="center">

<img src="assets/chub-logo.png" alt="CHUB logo" width="128" />

# ![CHUB](https://img.shields.io/badge/CHUB-463fbc?style=for-the-badge&labelColor=463fbc)

### Chodeus' Media Script Hub
**alpha version, this is still under active development**

A self-hosted, all-in-one media asset manager for your Plex/ARR stack.

[![MIT License](https://img.shields.io/badge/license-MIT-463fbc?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.8%2B-1992f3?style=flat-square)](https://www.python.org/)
[![Docker Image](https://img.shields.io/badge/ghcr.io-chodeus%2Fchub-463fbc?style=flat-square&logo=docker&logoColor=white)](https://github.com/chodeus/chub/pkgs/container/chub)
[![GitHub Issues](https://img.shields.io/github/issues/chodeus/chub?color=463fbc&style=flat-square)](https://github.com/chodeus/chub/issues)
[![GitHub Stars](https://img.shields.io/github/stars/chodeus/chub?color=53e8f0&style=flat-square)](https://github.com/chodeus/chub/stargazers)

</div>

---

## What is CHUB?

CHUB keeps a Plex library tidy. Point it at Radarr, Sonarr, Lidarr, and Plex, and it takes care of the boring chores on a schedule:

- **Posters** — rename them to match your library, optimize file sizes, re-apply brand or holiday borders, pull new ones from Google Drive, and clean up orphans.
- **Media** — find duplicates, flag low-rated or incomplete items, edit metadata inline with a full audit trail, and batch-import into Radarr or Sonarr.
- **Upkeep** — upgrade searches, rename sweeps, health checks, hardlink audits, ARR tag → Plex label sync.

You run it in Docker, open it in a browser, configure it once, and let it work.

---

## Screenshots

| Light | Dark |
| :---: | :---: |
| ![Dashboard light](docs/images/dashboard-light.png) | ![Dashboard dark](docs/images/dashboard-dark.png) |

---

## Quickstart

### Docker Compose (recommended)

Save this as `compose.yaml` and adjust the paths to your setup:

```yaml
services:
  chub:
    image: ghcr.io/chodeus/chub:latest
    container_name: chub
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      PUID: "1000"             # Unraid users: 99
      PGID: "1000"             # Unraid users: 100
      TZ: "America/Los_Angeles"
    volumes:
      - /srv/apps/chub/config:/config
      - /srv/apps/chub/posters:/posters
      - /srv/media:/media
      - /srv/kometa/assets:/kometa
```

Then:

```bash
docker compose up -d
```

Open <http://localhost:8000>, create your admin user, connect your Radarr / Sonarr / Plex under **Settings → Instances**, and enable the modules you want under **Settings → Modules**.

> **Rootless alternative.** Prefer not to let the container start as root? Replace the `PUID`/`PGID` env vars with `user: "99:100"` (or whatever uid:gid owns your appdata) and pre-`chown` the host config dir to match. The container then never runs as root — slightly more secure, but you own the host-side permissions. PUID/PGID is the easier default; `--user` is the hardened option.

Already have a `config.yml` from an older YAML-based version of this tool? Drop it into the mounted config dir before first launch — CHUB detects the older shape, preserves the original as a timestamped backup, and migrates the file in place. Details: **[Wiki → Configuration → Auto-migration](https://github.com/chodeus/chub/wiki/Configuration#-auto-migration-from-older-config-formats)**.

Full walk-through: **[Wiki → Installation](https://github.com/chodeus/chub/wiki/Installation)**.

### Other install methods

Single-command Docker, Unraid, and bare-metal options: **[Wiki → Installation](https://github.com/chodeus/chub/wiki/Installation)**.

---

## Security — read before exposing CHUB

**CHUB is built for a private network.** Run it on a LAN or behind a VPN. Before putting it anywhere else, take the steps below.

1. **Use a strong admin password.** First-run enforces 8+ characters; use more. Lose it and you reset with `docker compose run --rm chub python3 main.py --reset-auth`.
2. **If you want remote access, put CHUB behind a reverse proxy with TLS.** Add a second auth layer in front (Authelia, Authentik, Cloudflare Access). CHUB has built-in login and rate limiting, but no WAF or DDoS protection — it isn't meant to face the open internet alone.
3. **Set a webhook secret if webhooks leave your LAN.** Configure `general.webhook_secret` in **Settings → General**. Any inbound Sonarr/Radarr/Tautulli webhook must then include it. Without it, webhook URLs are unauthenticated — fine inside a LAN, not fine on the public internet. Wiring a webhook into Sonarr/Radarr is documented in the [Webhooks wiki page](https://github.com/chodeus/chub/wiki/Webhooks).
4. **Pin the image tag for production.** Use a specific digest or date tag instead of `:latest` if you care about reproducible deploys.
5. **Drop capabilities to harden the root window.** CHUB's entrypoint briefly runs as root to apply `PUID`/`PGID` before dropping to an unprivileged user. You can strip every capability except the four it actually uses for that handoff — the container then has no `NET_RAW`, `SYS_ADMIN`, mount, or module-loading powers even during init.

   ```yaml
   services:
     chub:
       # ...
       cap_drop: [ALL]
       cap_add: [CHOWN, SETUID, SETGID, FOWNER]
       security_opt:
         - no-new-privileges:true
   ```

   Or, for a fully rootless setup, replace `PUID`/`PGID` with `user: "99:100"` (or whatever uid:gid owns your appdata) and `chown` the host config dir to match — see the Quickstart note. Either approach removes meaningful attack surface; cap-drop is easier, `--user` is stricter.
6. **Report vulnerabilities privately.** See [SECURITY.md](SECURITY.md) for the disclosure process.

---

## Documentation

The GitHub Wiki is the full source:

- **[User Guide](https://github.com/chodeus/chub/wiki)** — installation, configuration, per-module walk-through, UI tour, webhooks, troubleshooting, FAQ.
- **[Developer Guide](https://github.com/chodeus/chub/wiki/Developer-Guide)** — REST API reference, extending CHUB with new modules, security internals.

---

## A note on AI-assisted development

I write large portions of CHUB's source, tests, and documentation with the help of an AI coding assistant (Anthropic's Claude). I review every change before it lands, but you should know what you're running: if a behavior, doc, or config option looks wrong, trust what the code actually does and [open an issue](https://github.com/chodeus/chub/issues).

---

## Credits

CHUB is a fork of [DAPS](https://github.com/Drazzilb08/daps) by **Drazzilb08** — thank you for the scripts and inspiration that made this possible.

Licensed under the [MIT License](LICENSE).

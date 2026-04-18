# Configuration

CHUB reads `${CONFIG_DIR}/config.yml` on startup (default `/config/config.yml` in the container). The schema is defined by Pydantic models in `backend/util/config.py` (`ChubConfig`).

You can edit `config.yml` directly, but the web UI (**Settings** pages) is the easier path — it writes back through `POST /api/config` with schema validation.

---

## Top-level layout

```yaml
schedule:          {}   # per-module cron or interval rules
instances:         {}   # Radarr / Sonarr / Lidarr / Plex connections
notifications:     {}   # per-module notification configs
general:           {}   # global knobs
user_interface:    {}   # theme preference
auth:              {}   # username + bcrypt hash + JWT secret

# Module sections (see Modules page for usage details)
sync_gdrive:       {}
unmatched_assets:  {}
poster_renamerr:   {}
border_replacerr:  {}
upgradinatorr:     {}
renameinatorr:     {}
nohl:              {}
labelarr:          {}
health_checkarr:   {}
jduparr:           {}
nestarr:           {}
poster_cleanarr:   {}
```

---

## `general`

```yaml
general:
  log_level: info              # debug | info | warning | error
  update_notifications: false  # surface new-release banner in UI
  max_logs: 9                  # rotate module log files at this count
  webhook_initial_delay: 30    # sec — delay before processing inbound webhook
  webhook_retry_delay: 60      # sec — between retry attempts
  webhook_max_retries: 3
  webhook_secret: ""           # empty = webhooks unauthenticated; set to require HMAC
  duplicate_exclude_groups: [] # group IDs the duplicates UI should ignore
```

If `webhook_secret` is non-empty, every call to `/api/webhooks/*` must include `X-Webhook-Secret: <secret>` or `?secret=<secret>`. See [Webhooks](Webhooks).

---

## `auth`

Managed by the web UI — do not hand-edit unless you know what you're doing.

```yaml
auth:
  username: admin
  password_hash: "$2b$12$..."   # bcrypt
  jwt_secret: "<random>"        # rotated on first launch
  token_expiry_hours: 24
```

To reset auth: stop CHUB, delete the `auth` section from `config.yml`, start it back up — you'll be prompted to create a new admin user.

---

## `instances`

Keys under `radarr`, `sonarr`, `lidarr`, and `plex` are the instance names you'll reference elsewhere in `config.yml`.

```yaml
instances:
  radarr:
    radarr_main:
      url: http://radarr:7878
      api: <api_key>
      enabled: true
    radarr_4k:
      url: http://radarr-4k:7878
      api: <api_key>
      enabled: true
  sonarr:
    sonarr_main:
      url: http://sonarr:8989
      api: <api_key>
  lidarr:
    lidarr_main:
      url: http://lidarr:8686
      api: <api_key>
  plex:
    plex_main:
      url: http://plex:32400
      api: <x_plex_token>
```

**SSRF guard**: outbound probes reject `169.254.169.254`, `metadata.google.internal`, reserved/link-local/multicast ranges, and non-`http(s)` schemes. Use routable IPs or hostnames.

---

## `schedule`

Every module can run on a cron expression, a fixed interval, or on demand only.

```yaml
schedule:
  poster_renamerr:
    type: cron
    expression: "0 */4 * * *"   # every 4h
  jduparr:
    type: interval
    minutes: 720                # every 12h
  upgradinatorr:
    type: cron
    expression: "15 3 * * *"    # daily at 03:15
  # Omit a module to leave it manual-only.
```

Independently, CHUB runs a built-in 6-hour **system tick** that writes `system_health_snapshots`. You don't configure it.

---

## `notifications`

One entry per module that supports notifications. Each entry is a free-form dict consumed by `backend/util/notification.py` — shape depends on the channel. Example Discord config:

```yaml
notifications:
  main:
    discord:
      enabled: true
      webhook: https://discord.com/api/webhooks/...
  poster_renamerr:
    discord:
      enabled: true
      webhook: https://discord.com/api/webhooks/...
      mention_role: "123456789"
  upgradinatorr:
    apprise:
      enabled: true
      url: "discord://..."
  health_checkarr:
    email:
      enabled: true
      from: chub@example.com
      to: [you@example.com]
      smtp_host: smtp.example.com
      smtp_port: 587
      username: chub
      password: <smtp_password>
```

---

## `user_interface`

```yaml
user_interface:
  theme: dark    # light | dark — persists across sessions
```

The **Settings → Interface** page writes this. Browser localStorage stores the active theme for the current device; `config.yml` is the server default.

---

## Module sections

Every module has its own section. Only common shapes are listed here — the full walkthrough is on [Modules](Modules).

### `poster_renamerr`

```yaml
poster_renamerr:
  log_level: info
  dry_run: false
  sync_posters: false
  action_type: copy                     # copy | move | hardlink
  asset_folders: false
  print_only_renames: false
  run_border_replacerr: false
  incremental_border_replacerr: false
  run_cleanarr: false
  report_unmatched_assets: false
  source_dirs: [/kometa]
  destination_dir: /posters
  instances:
    - radarr_main
    - sonarr_main
    - plex_main:
        library_names: ["Movies", "TV Shows"]
        add_posters: true
```

### `border_replacerr`

```yaml
border_replacerr:
  source_dirs: [/posters]
  destination_dir: /posters
  border_width: 26
  border_colors: ["#ff7300"]
  holidays:
    - name: halloween
      schedule: "10-01:10-31"
      colors: ["#FF6600", "#000000"]
```

### `upgradinatorr`

```yaml
upgradinatorr:
  dry_run: false
  instances_list:
    - instance: radarr_main
      count: 10
      tag_name: chub-upgradinatorr
      ignore_tag: ignore
      unattended: false
      search_mode: upgrade       # upgrade | missing | cutoff
```

### `labelarr`

```yaml
labelarr:
  mappings:
    - app_instance: sonarr_main
      labels: [watched, favorite]
      plex_instances:
        - instance: plex_main
          library_names: ["TV Shows"]
```

### Other modules

See [Modules](Modules) for `nohl`, `jduparr`, `nestarr`, `unmatched_assets`, `renameinatorr`, `health_checkarr`, `poster_cleanarr`, `sync_gdrive`.

---

## Secret handling

Responses from `GET /api/config` **redact** these fields to `********` before returning JSON:

- `api`, `api_key`
- `access_token`, `refresh_token`, `token`, `client_secret`
- `password_hash`, `jwt_secret`, `webhook_secret`

When the UI saves config back, any field still equal to `********` is replaced with the current on-disk value. This means you can edit non-sensitive fields in the UI without re-entering API keys.

If you hand-edit `config.yml`, keep the file at `0600` — it contains real secrets.

---

## Validating changes

CHUB validates the whole file on startup; an invalid config refuses to load. You can also dry-run validation:

```bash
docker compose run --rm chub python3 -c "from backend.util.config import load_config_cli; load_config_cli()"
```

The UI validates per-page before saving (`POST /api/config` returns 400 on schema failure, with the offending field path).

# Configuration

CHUB reads a single YAML file on startup: `config.yml`, kept in `${CONFIG_DIR}` (in Docker, that's `/config/config.yml` — i.e. the host folder you mounted as `/config`).

You can edit `config.yml` by hand, but the **Settings** pages in the web UI are the easier path — every Settings page writes back through a validated API. If you do hand-edit the file:

- Keep permissions at `0600` — it contains API keys.
- CHUB revalidates the whole file on startup. If validation fails, CHUB won't start and the container log tells you which field is wrong.

## What the file looks like

At the top level, `config.yml` has these sections:

```yaml
schedule:          {}   # when each module runs
instances:         {}   # your Radarr / Sonarr / Lidarr / Plex connections
notifications:     {}   # Discord / Email / Apprise per module
general:           {}   # global toggles
user_interface:    {}   # theme
auth:              {}   # your admin user (managed by the UI)

# One section per module
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

Unused module sections can be omitted entirely — CHUB uses safe defaults for anything missing.

## `general`

Global toggles, shown in **Settings → General**:

```yaml
general:
  log_level: info              # debug | info | warning | error
  update_notifications: false  # show a banner when a new CHUB release is out
  max_logs: 9                  # how many rotated log files to keep per module
  webhook_initial_delay: 30    # seconds to wait after an inbound webhook before acting
  webhook_retry_delay: 60      # seconds between retries
  webhook_max_retries: 3
  webhook_secret: ""           # empty = webhooks unauthenticated; set to require a shared secret
  duplicate_exclude_groups: [] # duplicate group IDs the UI should hide
```

If `webhook_secret` is set, every inbound webhook must send `X-Webhook-Secret: <secret>` (or `?secret=<secret>` in the URL). See [Webhooks](Webhooks).

## `auth`

Managed by the web UI. Don't edit unless you're trying to reset things.

```yaml
auth:
  username: admin
  password_hash: "$2b$12$..."
  jwt_secret: "<random>"
  token_expiry_hours: 24
```

To reset the admin password, see [Installation → Resetting the admin password](Installation#resetting-the-admin-password).

## `instances`

Your Radarr, Sonarr, Lidarr, and Plex connections. The key under each service is the name you'll reference elsewhere in `config.yml` (`radarr_main`, `sonarr_4k`, etc.).

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

For Plex, the `api` field is the `X-Plex-Token`, not your Plex Pass login. Plex has a [short guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) for finding your token.

**About URLs**: CHUB blocks outbound calls to reserved / cloud-metadata / link-local ranges (this is the SSRF guard — it prevents a misconfigured URL from probing sensitive internal endpoints). Use a routable IP or a hostname your container can resolve. `http://radarr:7878` works if CHUB and Radarr share a Docker network.

**Testing**: in **Settings → Instances**, each instance has a **Test** button. Run it after adding or editing an entry.

## `schedule`

One entry per module that should run on a schedule. Anything not listed here is manual-only (triggered by you from the dashboard, or by a webhook).

```yaml
schedule:
  poster_renamerr:
    type: cron
    expression: "0 */4 * * *"   # every 4 hours
  jduparr:
    type: interval
    minutes: 720                # every 12 hours
  upgradinatorr:
    type: cron
    expression: "15 3 * * *"    # daily at 03:15
```

`type` is either `cron` (with `expression`) or `interval` (with `minutes`). The **Settings → Schedule** page has a form that writes this for you.

CHUB also runs a built-in system-health probe every 6 hours. You don't configure it.

## `notifications`

One entry per module that should send notifications, plus an optional `main` entry for global notifications.

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

Discord, Email, and Apprise are supported. Apprise's URL format covers dozens of other services — see the [Apprise README](https://github.com/caronc/apprise#supported-notifications) for the catalog.

## `user_interface`

```yaml
user_interface:
  theme: dark    # light | dark
```

This is the server-wide default. Each browser also remembers its own choice, so toggling the theme in the header sticks on that device.

## Module sections

Every module has its own section. See [Modules](Modules) for what each one does and the full set of fields; a few common shapes:

### `poster_renamerr`

```yaml
poster_renamerr:
  dry_run: false
  action_type: copy                     # copy | move | hardlink
  source_dirs: [/kometa]
  destination_dir: /posters
  run_border_replacerr: false
  run_cleanarr: false
  report_unmatched_assets: false
  instances:
    - radarr_main
    - sonarr_main
    - plex_main:
        library_names: ["Movies", "TV Shows"]
        add_posters: true
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

## How secrets are handled

When CHUB returns your config to the UI, it replaces these fields with `********` so they don't leak into browser storage or screenshots:

- `api`, `api_key`
- `access_token`, `refresh_token`, `token`, `client_secret`
- `password_hash`, `jwt_secret`, `webhook_secret`

When you save the config back through the UI, any field still equal to `********` is kept as-is — so editing non-sensitive fields in the UI won't wipe your API keys.

## If CHUB won't start because of a bad config

The container log prints which field failed validation. Either fix the field or remove the bad section and restart — CHUB will fall back to defaults for anything missing.

```bash
docker compose logs chub
```

See [Troubleshooting](Troubleshooting) for more.

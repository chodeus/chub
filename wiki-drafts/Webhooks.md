# Webhooks

CHUB accepts inbound webhooks from Sonarr, Radarr, and Tautulli to trigger actions like poster rename-on-import and orphaned-poster cleanup. Endpoints live under `/api/webhooks/*`.

---

## Auth

Webhook authentication is **optional** and off by default. If you set `general.webhook_secret` in `config.yml`, every inbound request must prove knowledge of it:

- **Header** (preferred): `X-Webhook-Secret: <secret>`
- **Query param** (for services that can't set headers): `?secret=<secret>`

CHUB compares using HMAC-safe string compare. A wrong or missing secret returns `401`.

If `webhook_secret` is empty, webhooks are unauthenticated — same posture as Sonarr/Radarr themselves. This is fine on a trusted local network; set a secret if you expose webhook URLs beyond it.

---

## Endpoints

### `POST /api/webhooks/poster/add`

**Source:** Sonarr / Radarr `OnImport` or `OnRename` events.

**What it does:** enqueues a `poster_renamerr` job scoped to the imported item — so newly-downloaded media gets its poster renamed + uploaded right away instead of waiting for the next scheduled run.

### `POST /api/webhooks/unmatched/process`

**Source:** any scheduler (cron service, HA automation, etc.).

**What it does:** enqueues an `unmatched_assets` scan to refresh the report.

### `GET /api/webhooks/unmatched/status`

Current unmatched-asset counts — useful for dashboards / uptime probes.

### `POST /api/webhooks/cleanarr/process`

**What it does:** enqueues a `poster_cleanarr` run.

### `GET /api/webhooks/cleanarr/status`

Current orphaned-poster count.

---

## Wiring Sonarr / Radarr

1. Go to **Settings → Connect → Add → Webhook** in Sonarr / Radarr.
2. **URL:** `http://<chub-host>:8000/api/webhooks/poster/add`
3. **Method:** `POST`
4. **Triggers:** at minimum `On Import` and `On Rename`. Optional: `On Movie Delete` / `On Series Delete`.
5. **Headers:** add `X-Webhook-Secret: <your secret>` if you set one.
6. **Test** — Sonarr/Radarr's test button fires a `Test` event; CHUB responds `200` and logs the origin.

CHUB's UI has a helper page at **Settings → Webhooks** that generates ready-to-paste URLs with the secret already appended.

---

## Wiring Tautulli

1. **Settings → Notification Agents → Add Webhook**
2. **URL:** `http://<chub-host>:8000/api/webhooks/poster/add`
3. **Triggers:** Recently Added (optional — mainly useful if you use Tautulli as a unifying notifier rather than direct Sonarr/Radarr hooks).
4. **Data format:** JSON. Leave template blank unless you know what you're overriding.

---

## Origin tracking

Every webhook-created job records an `origin` block in its payload:

```json
{
  "origin": {
    "client_host": "192.168.1.42",
    "endpoint": "/api/webhooks/poster/add",
    "event_type": "OnImport",
    "user_agent": "Sonarr/4.0.0"
  }
}
```

Aggregate view:

```
GET /api/jobs/webhook-origins?days=7
```

Returns a count per `(client_host, endpoint, event_type)` combination — handy for spotting noisy integrations or unexpected callers.

---

## Retry + back-off

If a webhook handler queues a job but the underlying module fails, the webhook doesn't retry — the job lives in the normal queue with its own retry semantics. But if the inbound call itself errors (e.g. CHUB is mid-restart), Sonarr/Radarr will retry per their own settings.

CHUB's own retry knobs apply when CHUB is the *sender* (notifications):

```yaml
general:
  webhook_initial_delay: 30   # sec
  webhook_retry_delay: 60
  webhook_max_retries: 3
```

---

## Troubleshooting

- **401 Unauthorized** — `webhook_secret` is set but the header/query param is missing or wrong. Copy the URL from **Settings → Webhooks** to get the correctly-signed version.
- **404 Not Found** — path typo; every endpoint is under `/api/webhooks/*`, not `/webhook/*`.
- **200 but nothing happens** — check the Jobs page; the webhook may have created a job that failed or was filtered. Inspect `GET /api/jobs?module=poster_renamerr&status=failed`.
- **Noisy origins** — check `/api/jobs/webhook-origins?days=7`; if a source is firing way too often, narrow its trigger list in Sonarr/Radarr.

See [Troubleshooting](Troubleshooting) for more.

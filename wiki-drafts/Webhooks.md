# Webhooks

CHUB can react to Sonarr, Radarr, and Tautulli events so poster rename and cleanup jobs fire the moment a new item arrives, instead of waiting for the next scheduled run. Every webhook URL is under `/api/webhooks/*`.

## Auth

Webhook authentication is **optional** and off by default. If you set `general.webhook_secret` in `config.yml` (or via **Settings → General** in the UI), every inbound request has to prove it knows the secret:

- Preferred: `X-Webhook-Secret: <secret>` HTTP header
- Fallback for services that can't send custom headers: `?secret=<secret>` query parameter

A wrong or missing secret returns `401`. If `webhook_secret` is empty, webhooks run unauthenticated — fine on a trusted LAN, but don't expose unauthenticated webhook URLs to the open internet.

## The five endpoints

### `POST /api/webhooks/poster/add`

**Who calls it:** Sonarr / Radarr on `OnImport` or `OnRename` events (Tautulli also works but is usually redundant).

**What CHUB does:** enqueues a poster-processing job scoped to the item in the payload, so the new download gets its poster renamed and moved right away. Duplicate webhooks for the same item are debounced for 5 seconds so a burst doesn't queue ten copies.

**Test events:** Sonarr and Radarr send an `eventType: "Test"` when you press their "Test" button; CHUB recognizes it, returns `200`, and logs the source.

### `GET /api/webhooks/unmatched/status`

Returns the current unmatched-assets summary — how many posters don't have a media match. Useful for dashboards and uptime probes.

### `POST /api/webhooks/unmatched/process`

Enqueues an `unmatched_assets` run to refresh the report. Anything that can send an HTTP POST can trigger this (cron, Home Assistant, a shortcut on your phone).

### `GET /api/webhooks/cleanarr/status`

Returns the current orphaned-poster count.

### `POST /api/webhooks/cleanarr/process`

Enqueues a `poster_cleanarr` run.

## Wiring Sonarr and Radarr

1. Open Sonarr (or Radarr) and go to **Settings → Connect → + → Webhook**.
2. **URL:** `http://<chub-host>:8000/api/webhooks/poster/add`
3. **Method:** `POST`
4. **Triggers:** at a minimum check **On Import** and **On Rename**. **On Movie Delete** / **On Series Delete** are optional if you want CHUB to clean up after deletions.
5. **Headers:** if you set a webhook secret, add `X-Webhook-Secret: <your secret>` here.
6. Click **Test** — Sonarr/Radarr fires a `Test` event; CHUB returns `200` and records the origin.
7. Click **Save**.

Tip: CHUB's **Settings → Webhooks** page generates ready-to-paste URLs with the secret already applied.

## Wiring Tautulli

1. **Settings → Notification Agents → Add a new notification agent → Webhook**.
2. **URL:** `http://<chub-host>:8000/api/webhooks/poster/add`
3. **Triggers:** Recently Added is usually enough. (Tautulli webhooks are mostly useful if you want a single poster-trigger source that covers events Sonarr/Radarr don't emit.)
4. **Data format:** JSON. Leave the template blank unless you know what you're overriding.

## Origin tracking

Every webhook-created job records who called it:

```json
{
  "origin": {
    "source": "webhook",
    "endpoint": "poster/add",
    "client_host": "192.168.1.42",
    "event_type": "OnImport",
    "user_agent": "Sonarr/4.0.0"
  }
}
```

Aggregate view: `GET /api/jobs/webhook-origins?days=7`. You'll see a count per `(client_host, endpoint, event_type)` combination — handy for spotting noisy integrations or unexpected callers.

## Retry behaviour

If CHUB enqueues a job but the underlying module later fails, the webhook doesn't retry — the job lives in the normal queue and follows its own retry rules. If the inbound webhook call itself errors (for instance, CHUB is mid-restart), Sonarr/Radarr will retry per their own settings.

CHUB's own retry knobs apply when CHUB is the one *sending* a webhook (outbound notifications):

```yaml
general:
  webhook_initial_delay: 30   # seconds between receiving a hook and acting
  webhook_retry_delay: 60     # seconds between failed-send retries
  webhook_max_retries: 3
```

## Troubleshooting

- **`401 Unauthorized`** — your `webhook_secret` is set but the caller isn't sending the header or `?secret=`. Copy the URL from **Settings → Webhooks** to get a version with the secret already applied.
- **`404 Not Found`** — path typo. Every endpoint is under `/api/webhooks/*`, not `/webhook/*`.
- **`200` but nothing happens** — check **Settings → Jobs**. The webhook probably created a job that failed downstream. Filter by module and status to find it.
- **Sonarr says "Test connection failed"** — it's almost always a network issue: Sonarr can't reach the CHUB host/port. Verify from inside Sonarr's container: `curl -I http://chub:8000/api/health`.
- **Duplicate events** — within a 5-second window, identical payloads are silently debounced. That's a feature; if you're seeing unexpected silence, check the debug log.

See [Troubleshooting](Troubleshooting) for more.

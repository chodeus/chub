# CHUB — Architecture

CHUB is a self-hosted media-asset manager. A React single-page app talks to a FastAPI backend that orchestrates scheduled modules against Plex, Radarr/Sonarr/Lidarr, Google Drive, and a local SQLite cache.

---

## System overview

```
                    ┌──────────────────────────────┐
                    │  Browser (React + Vite SPA)  │
                    │  • pages, components, hooks  │
                    │  • EventSource (SSE)         │
                    └──────────────┬───────────────┘
                                   │ HTTP + SSE (/api/*)
                    ┌──────────────┴───────────────┐
                    │   FastAPI backend (main.py)  │
                    │  ┌────────────────────────┐  │
                    │  │ routers                │  │
                    │  │  auth media posters    │  │
                    │  │  modules jobs system   │  │
                    │  │  schedule webhooks …   │  │
                    │  └───────────┬────────────┘  │
                    │              │                │
                    │  ┌───────────┴────────────┐  │
                    │  │ orchestrator / workers │  │
                    │  │  job_processor         │  │
                    │  │  scheduler             │  │
                    │  │  webhook_processor     │  │
                    │  └───────────┬────────────┘  │
                    └──────────────┼───────────────┘
                                   │
        ┌──────────────┬───────────┼───────────────┬───────────────┐
        │              │           │               │               │
   ┌────┴────┐   ┌─────┴────┐ ┌────┴────┐   ┌──────┴─────┐  ┌──────┴─────┐
   │ SQLite  │   │ Radarr/  │ │  Plex   │   │  Google    │  │  Filesystem│
   │ chub.db │   │ Sonarr/  │ │  API    │   │  Drive /   │  │  posters,  │
   │         │   │ Lidarr   │ │         │   │  rclone    │  │  media,    │
   └─────────┘   └──────────┘ └─────────┘   └────────────┘  │  kometa    │
                                                            └────────────┘
```

All state lives in `chub.db` (SQLite) and the configured filesystem volumes. There is no external queue or cache — the backend process owns the job queue, scheduler, and SSE fanout in memory.

---

## Repository layout

```
backend/
├── api/                # FastAPI routers (one per resource)
│   ├── auth.py
│   ├── media.py        │ media_api.py
│   ├── posters.py
│   ├── modules.py
│   ├── jobs.py
│   ├── schedule.py
│   ├── instances.py
│   ├── notifications.py
│   ├── webhooks.py
│   ├── system.py
│   ├── logs.py
│   ├── labelarr.py  │ nestarr.py
│   ├── config.py
│   └── server.py       # FastAPI app factory + router registration
├── modules/            # Scheduled/on-demand work units
│   ├── poster_renamerr.py
│   ├── poster_cleanarr.py
│   ├── border_replacerr.py
│   ├── labelarr.py
│   ├── jduparr.py
│   ├── nohl.py
│   ├── unmatched_assets.py
│   ├── upgradinatorr.py
│   ├── renameinatorr.py
│   ├── health_checkarr.py
│   ├── nestarr.py
│   └── sync_gdrive.py
└── util/
    ├── base_module.py        # ChubModule ABC + cooperative cancellation
    ├── job_processor.py      # queue, worker pool, cancel registry
    ├── scheduler.py          # cron/interval module scheduling + system tick
    ├── module_orchestrator.py
    ├── webhook_processor.py
    ├── rate_limiter.py       # token-bucket for auth
    ├── ssrf_guard.py         # blocks metadata IPs on outbound probes
    ├── path_safety.py        # null-byte / dash-prefix validation
    ├── logger.py             # SmartRedactionFilter (secrets scrub)
    ├── config.py             # ChubConfig loader
    ├── auth.py               # JWT + bcrypt
    ├── arr.py │ plex.py │ plex_metadata.py
    └── database/             # SQLite schema + per-table helpers

frontend/src/
├── App.jsx                  # provider tree + routes
├── components/
│   ├── Layout.jsx           # floating content panel
│   ├── LayoutHeader.jsx     # CHUB banner, theme toggle
│   ├── LayoutSidebar.jsx    # nav, small-caps section dividers
│   ├── ui/                  # primitives: button, card, modal, fields
│   └── …
├── pages/                   # route-level components
├── contexts/                # Theme, Toast, UIState, Form, Toolbar, Search
├── hooks/                   # useApiData, useModuleEvents, useSearch, …
├── utils/api/               # apiCore + per-resource clients
└── css/
    ├── theme/tokens.css     # radii, font families
    ├── theme/light.css      # indigo-led cool palette
    ├── theme/dark.css
    └── components/          # BEM-named component CSS
```

---

## Module architecture (`ChubModule`)

`backend/util/base_module.py` defines the abstract base class every scheduled module extends:

```python
class ChubModule(ABC):
    def __init__(self, config=None, logger=None):
        self._cancel_event: Optional[threading.Event] = None
        self.full_config = load_config()
        self.config = getattr(self.full_config, self._get_module_name())
        self.logger = logger.get_adapter(name) if logger else Logger(...)

    def set_cancel_event(self, event): self._cancel_event = event
    def is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()
```

Each module class is registered in `backend/modules/__init__.py`'s `MODULES` dict. `ChubModule._get_module_name()` walks that registry and matches on class identity — this is how the module discovers its own config section.

### Cooperative cancellation

- `job_processor.py` owns a **cancel registry** mapping `job_id` → `threading.Event`.
- `DELETE /api/modules/{name}/execution/{job_id}` sets the event.
- Long-running modules check `self.is_cancelled()` inside loops and exit early.
- Currently wired: `upgradinatorr`, `jduparr`, `nohl`, `sync_gdrive`, `unmatched_assets`.
- Not yet wired (tracked in `CLAUDE.md`): `poster_renamerr`, `labelarr`, `nestarr`, `renameinatorr`, `health_checkarr`, `border_replacerr`, `poster_cleanarr`.

### Lifecycle

```
scheduler tick / API request / webhook
        │
        ▼
job_processor.enqueue(job)
        │
        ▼
worker thread: instantiate ChubModule subclass
        │  → module.set_cancel_event(event)
        │  → module.run()
        ▼
persist result to jobs table, emit SSE update
```

---

## Job processor

`backend/util/job_processor.py`:

- In-process queue (thread-safe) with a fixed worker pool.
- Every job is persisted to the `jobs` table with `status`, `job_type`, `module`, `payload`, `result`, and timestamps.
- Cancel events are registered in a dict keyed by `job_id`; cancelling looks up the event and sets it.
- Webhook-originated jobs carry an `origin: {client_host, endpoint, event_type, user_agent}` block in their payload — summarised by `GET /api/jobs/webhook-origins?days=7`.
- `GET /api/jobs` supports DB-level filtering (`status`, `job_type`, `module`) + pagination (`limit`, `offset`).
- `DELETE /api/jobs/old?days=30` purges completed jobs.

---

## Scheduler

`backend/util/scheduler.py`:

- Reads `config.schedule` (per-module cron / interval rules) and enqueues jobs on tick.
- **System tick** runs every 6 hours regardless of config — it probes every configured instance (Radarr/Sonarr/Lidarr/Plex/GDrive) and writes a row to `system_health_snapshots`. Rows older than 30 days are pruned automatically.
- Snapshots exposed via `GET /api/system/health/snapshots`.

---

## Webhooks

`backend/api/webhooks.py` + `backend/util/webhook_processor.py`:

- Accepts Sonarr/Radarr/Tautulli event payloads.
- Optional shared-secret auth: if `general.webhook_secret` is set, requests must provide either `X-Webhook-Secret` header or `?secret=` query param (HMAC-compared). If unset, webhooks are accepted unauthenticated (matches Sonarr/Radarr's default posture).
- Each inbound webhook creates a job with origin metadata — enables downstream filtering and auditing.

---

## Real-time updates (SSE)

`GET /api/modules/events` streams module-run state changes as Server-Sent Events:

- Backend polls `run_state` every 2 s, diffs against the last snapshot, pushes only changes.
- Auth: `Authorization: Bearer <jwt>` or `?token=<jwt>` (EventSource does not support custom headers natively).
- Frontend hook: `frontend/src/hooks/useModuleEvents.js` connects with auto-reconnect and exponential backoff.
- Falls back transparently to polling via `useModuleExecution` if SSE is unavailable.

---

## Database

Schema is defined in `backend/util/database/schema.py`; additive changes use `add_missing_columns` so upgrades don't require migrations. Key tables:

| Table | Purpose |
| --- | --- |
| `media_cache` | Unified Radarr/Sonarr/Lidarr item cache with `created_at` for time-window queries |
| `media_edit_history` | Audit trail: every inline metadata edit (field, old, new, edited_by, ts) |
| `collection_cache` | Plex collection snapshots + poster_collection-from-tag output |
| `plex_cache` | Plex library items keyed by ratingKey |
| `poster_cache` | File poster index with `width`, `height`, `created_at` |
| `jobs` | Queue + history; supports filtering/pagination |
| `system_health_snapshots` | 6-hour cadence; 30-day retention |
| `run_state` | Latest per-module run state (drives SSE + dashboard) |
| `users` | bcrypt-hashed auth |

Per-table helpers live in `backend/util/database/*.py` (one file per concern).

---

## Frontend

### Stack

- React 19 + Vite 6 (dev server on `:5174`, proxies `/api` to `:8000`)
- React Router DOM 7
- PropTypes for runtime validation (no TypeScript)
- CSS custom properties for theming (no Tailwind, no CSS-in-JS)
- Context API for state (no Redux/Zustand)

### Provider tree (`App.jsx`)

```
ToastProvider
└─ ThemeProvider
   └─ ErrorProvider
      └─ UIStateProvider
         └─ BrowserRouter
            └─ SearchCoordinatorProvider
               └─ RouteErrorBoundary
                  └─ <Routes>
```

### Component pattern: three tiers

1. **Primitives** (`components/ui/`): thin HTML wrappers — `InputBase`, `ButtonBase`, `CardContainer`.
2. **Basic fields** (`components/fields/basic/`): compose primitives with `FieldWrapper` + optional `FormContext`. `useOptionalFormField` lets every field work standalone or inside a `FormProvider`.
3. **Compound components**: static subcomponents like `Card.Header`, `Card.Body`, `Form.Section`.

### API client (`utils/api/core.js`)

- In-memory response cache keyed by URL (`cacheTTL = 300_000` default)
- In-flight request deduplication (same URL → same promise)
- Pattern-based cache invalidation on POST/PUT/DELETE
- `APIError` class with `isClientError()`, `isServerError()`, `isRetryable()`
- `AbortController` timeouts (30 s default)

### Error boundaries

- **`PageErrorBoundary`** — per-route; full error UI with retry, navigate home, copy-error-to-clipboard.
- **`FeatureErrorBoundary`** — feature-level graceful degradation; auto-disables feature after 3 retries.
- **`ErrorContext`** — global ring buffer (last 10) + `useErrorRecovery` hook.

### Theme system

- `frontend/src/css/theme/tokens.css` — theme-agnostic radii + font families
- `frontend/src/css/theme/light.css` / `dark.css` — colour tokens on `[data-theme="light|dark"]`
- `ThemeContext` + `themeManager` toggle the `[data-theme]` attribute on `<html>`
- Pastel "badge" palette (`--badge-1..5-bg/fg`) drives the dashboard quick-start icons

### CSS layers

```css
@layer reset, base, components, utilities, pages;
```

Utilities always win over component rules. Stylelint enforces BEM naming (`.block__element--modifier`) in `components/`; the `utilities/` tree is excluded.

### Build / deploy

- `vite build` emits to `frontend/dist/`.
- `scripts/build.sh` copies `dist/` into `backend/api/templates/` so FastAPI can serve it as static files.
- FastAPI mounts `/assets` and a SPA catch-all that returns `index.html` for any non-`/api/*` path.

---

## Security infrastructure

- **`rate_limiter.py`** — token bucket (1 req / 5 s, burst 5) applied to `POST /api/auth/login`.
- **`ssrf_guard.py`** — blocks `169.254.169.254`, `metadata.google.internal`, reserved/link-local/multicast, and non-http(s) schemes. Enforced on instance-health probes and scheduler snapshots.
- **`path_safety.py`** — rejects null bytes and values starting with `-` on path-valued config (prevents arg-smuggling in list-form `subprocess` calls for `jduparr`, `sync_gdrive`).
- **`logger.py` `SmartRedactionFilter`** — scrubs JWTs, Bearer tokens, bcrypt hashes, Radarr/Sonarr `X-Api-Key`, `X-Plex-Token`, JWT/webhook secrets, Discord webhook URLs, Google OAuth IDs/secrets, AWS keys, GitHub tokens.
- **Auth** — bcrypt password hashing, JWT session tokens stored in `localStorage['chub-auth-token']`, webhook shared-secret via HMAC compare.

---

## Relevant endpoint surface

A non-exhaustive snapshot — see the wiki `API.md` for the full reference.

| Domain | Notable endpoints |
| --- | --- |
| Auth | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` |
| Modules | `GET /api/modules`, `POST /api/modules/{name}/run`, `DELETE /api/modules/{name}/execution/{job_id}`, `GET /api/modules/events` (SSE) |
| Media | `GET /api/media`, `POST /api/media/import`, `GET /api/media/duplicates?similarity=0.8`, `POST /api/media/duplicates/{group_id}/resolve`, `GET /api/media/stats?period=30d`, `GET /api/media/low-rated`, `GET /api/media/incomplete-metadata`, `GET /api/media/{id}/history`, `POST /api/media/collections/from-tag` |
| Posters | `POST /api/posters/optimize`, `GET /api/posters/{id}/thumbnail`, `POST /api/posters/{id}/download`, `GET /api/posters/low-resolution`, `GET /api/posters/added-since`, `POST /api/posters/backfill-dimensions` |
| Jobs | `GET /api/jobs`, `DELETE /api/jobs/old?days=30`, `GET /api/jobs/webhook-origins` |
| System | `GET /api/system/health/snapshots`, `GET /api/system/digest`, `GET /api/system/cleanup-candidates` |
| Labelarr | `POST /api/labelarr/bulk-sync` |

---

## Credits

CHUB builds on the original [DAPS](https://github.com/Drazzilb08/daps) project by **Drazzilb08**. The module set and many of the Plex/ARR integration patterns originated there.

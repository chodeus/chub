# Central Plex instance + library catalog with per-module `plex_scope`

- **Date:** 2026-06-23
- **Status:** Design — awaiting implementation plan
- **Branch impact:** shared files only → lands on `main`, `develop` stays byte-identical via `git merge main`

## Problem

Plex instance + library scope is declared in **five module configs across three
different shapes**, with five different UI treatments:

| Module | Current shape |
|---|---|
| `poster_renamerr` | `instances: List[Union[str, Dict[name, {library_names, add_posters}]]]` |
| `asset_renamerr` | same dict shape |
| `unmatched_assets` | `instances: List[Union[str, Dict[name, Any]]]` (library_names via `.get`) |
| `labelarr` | `mappings[].plex_instances[].{instance, library_names}` (relational) |
| `nestarr` | `library_mappings[].plex_instances[].{instance, library_names}` (relational) |

Plus `poster_cleanarr` / `plex_maintenance`, which take Plex as `List[str]` with
no library scope.

Consequences observed:

- The `List[Union[str, Dict]]` shape is error-prone — a stale migrator rule
  silently flattened the supported Plex dict form on `unmatched_assets`,
  destroying per-library scope (fixed separately; this design retires the shape
  that caused it).
- The same concept is duplicated per module, so library names are repeated and
  drift independently.
- `unmatched_assets` supports Plex collection scoping in the backend, but its UI
  is ARR-only — the feature is unreachable/undurable through the app.

## Goal

Capture Plex instances + their libraries in **one place** (Settings →
Instances), with Plex as the live source of truth, and have each module store
only its **opt-in subset** in a single shared shape, edited through one shared
widget. Retire the `List[Union[str, Dict]]` shape.

## Principles

### P0 — Single source of definition

Instances (and Plex libraries) are defined/discovered in exactly one place:
**Settings → Instances**. Every module consumes that catalog read-only and
stores only its opt-in selection. A module settings page must never create or
edit an instance connection.

### P1 — Plex is the source of truth for libraries

The library list is always discovered live from Plex (existing endpoint) and
cached for the UI. It is never persisted as curated config, so it cannot drift
from what Plex actually has.

## Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Catalog source | **Live + cached** (Plex is truth); no stored/curated library list |
| 2 | Empty `library_names` semantics | **Empty = all libraries** of that instance; instance absent = module ignores it |
| 3 | Field structure | **Split**: `instances: List[str]` (ARR) + `plex_scope: List[PlexScope]` |
| 4 | Module conversion scope | `poster_renamerr`, `asset_renamerr`, `unmatched_assets`; relational + instance-only modules keep their shape but use the shared catalog/widget |
| 5 | `add_posters` | **Optional field on shared `PlexScope`**, honored only by uploader modules |
| 6 | Migration | **Auto-migrate + persist** (existing migrator pattern: detect → back up → rewrite) |
| 7 | Plex card libraries | **Explicit "Libraries (catalog)" section** on the Plex InstanceCard |

## Data model

New shared Pydantic model (in `backend/util/config.py`):

```python
class PlexScope(BaseModel):
    instance: str
    library_names: List[str] = []   # [] = all libraries of this instance
    add_posters: bool = False       # honored only by uploader modules
```

Converted modules replace their `instances: List[Union[str, Dict]]` with:

```python
instances: List[str]            # ARR only (radarr / sonarr / lidarr)
plex_scope: List[PlexScope]     # Plex selection + per-library narrowing
```

**Uniform semantic rule** (one shared helper, used by every consumer):

- Instance **absent** from `plex_scope` → module ignores that Plex instance.
- Present with **empty** `library_names` → all of that instance's libraries.
- Present with names → that subset only.

## Central catalog (Settings → Instances)

- Settings → Instances ([`InstancesPage.jsx`](../../../frontend/src/pages/settings/InstancesPage.jsx))
  is the one place all four instance types are defined. It already discovers
  Plex libraries (`librariesData` state) and shows them on the Plex card.
- Add a **cached** read path over the existing live discovery endpoint
  `GET /api/plex/{instance}/libraries`
  ([`instances.py:507`](../../../backend/api/instances.py), currently uncached).
  A short server-side TTL cache (mechanism pinned in the implementation plan —
  in-memory TTL preferred, reusing the spirit of the existing Plex staleness
  guards). The **same cached data** feeds both the Instances page and the
  module pickers — one fetch, one source.
- The catalog is read-only convenience for the UI + validation; it is never
  persisted as config. **No new config section.**

## Frontend

### Settings → Instances

- Defines instances (Radarr/Sonarr/Lidarr/Plex) — connection/identity only.
- **Plex InstanceCard gains an explicit "Libraries (catalog)" section**: a
  labelled list with library-type icons and a refresh control, so it visibly
  reads as the source catalog modules draw from (today libraries appear only in
  the stats area — [`InstanceCard.jsx:103`](../../../frontend/src/components/instances/InstanceCard.jsx)).

### Module settings pages

- One shared library-picker component drives every module. It only
  **references/opts into** instances already defined on Settings → Instances —
  it never redefines a connection.
- ARR instances → checkboxes → `instances: List[str]`.
- Plex instances → per-instance library multiselect populated from the cached
  catalog → `plex_scope: List[PlexScope]`.
- The "Upload to this Plex instance" toggle renders only where the module's
  schema sets `add_posters_option: true` (poster_renamerr / asset_renamerr) —
  reusing the existing schema flag.
- Side effect: `unmatched_assets` gains a Plex picker, so collection reporting
  becomes configurable in the UI (empty = all libraries).

## Runtime consumption

- `build_instance_map` / `gather_media_and_collections`
  ([`connector.py:1206`](../../../backend/util/connector.py)) and
  `compute_instance_filters`
  ([`unmatched_assets.py:37`](../../../backend/modules/unmatched_assets.py))
  read from `instances` (ARR) + `plex_scope` (Plex) instead of the mixed list.
- The "empty = all libraries" rule is implemented **once** in a shared helper so
  every module behaves identically.

### Behaviour-change note (unmatched_assets)

Today, a bare/absent Plex entry → no collections reported. Under the new rule, a
Plex entry with empty `library_names` → all libraries' collections. The migrator
preserves each user's **current effective scope** (see below) so no existing
report silently changes.

### Behaviour-change note (poster_renamerr / asset_renamerr) — empty libraries

poster/asset renamerr have **two conflicting empty-library behaviours today**:

- Plex **sync** path — `_determine_target_libraries`
  ([`connector.py:777`](../../../backend/util/connector.py)): empty → all
  libraries.
- **Match** path — `gather_media_and_collections`
  ([`connector.py:1220`](../../../backend/util/connector.py)): empty → pulls
  **no** collections for matching.

Net effect for a Plex instance with no libraries selected: media posters upload
(driven by `add_posters`, independent of libraries), but **no collection posters**
are matched/applied. This "Plex selected, libraries empty, upload on" state is
**common**, because ticking a Plex instance in the current UI starts with empty
libraries.

A uniform `empty = all` would silently start matching/applying collection posters
across every library for these users. **Decision: option 1 — preserve current
effective behaviour.** The migrator must encode the old "selected for upload, no
collections" intent rather than letting empty become all-collections. The exact
encoding (per-entry collection toggle vs explicit no-collections marker) is an
implementation-plan item.

**Scope of impact:** this only affects users who (a) have Plex collections **and**
(b) have an empty-library Plex entry. Users with no Plex collections are
unaffected either way (`collections_cache` is empty, so both rules yield nothing).

## Migration (auto-migrate + persist)

New migrator rules in
[`config_migrator.py`](../../../backend/util/config_migrator.py), one per
converted module, building on the existing infrastructure:

- Split the old `instances` list into ARR strings (→ `instances`) and Plex
  entries (→ `plex_scope`):
  - `{name: {library_names, add_posters}}` → `PlexScope(instance=name, ...)`.
  - bare Plex **string** → `PlexScope(instance=name, library_names=[])`
    (= all libraries — matches old bare-string behaviour).
  - **poster/asset only — empty `library_names` preservation (option 1):** an old
    Plex entry with empty `library_names` currently pulls **no** collections. The
    migrator must NOT convert this to all-collections; it preserves the
    no-collections intent (encoding TBD in the plan). `add_posters` carries over
    unchanged so upload behaviour is identical.
- Detection: the old Plex-in-`instances` shape becomes a migration trigger (it
  is now legacy relative to the new schema).
- Idempotent; backs up to `config.yml.legacy-<timestamp>.yml` and rewrites
  `config.yml`, exactly as the current migrator does.
- The separately-shipped `unmatched_assets` fix folds in: the unmatched dict
  form now migrates **into** `plex_scope` rather than being preserved in place.

## Relational + instance-only modules (shape unchanged, shared UX)

- `nestarr` and `labelarr` keep their `…_mappings[].plex_instances[]` relational
  shape — an ARR↔library mapping cannot collapse to a flat subset — but adopt
  the **same catalog + library-picker widget** for choosing libraries. No config
  migration for these two.
- `poster_cleanarr` / `plex_maintenance` reuse the shared instance picker (Plex,
  no libraries).

## Branch-model compliance

All touched files are shared (`config.py`, `config_migrator.py`, `connector.py`,
the three modules, `settings_schema.js`, `InstancesPage.jsx`/`InstanceCard.jsx`,
the picker widget, the libraries API). They land on `main`; `develop` then
`git merge main` preserves the added-files-only invariant. No extension code is
involved.

## Testing

- **Migrator:** per-module split; bare-string → all-libraries; dict → subset;
  idempotency; backup written; mixed ARR + Plex lists.
- **Schema:** `PlexScope` validation; `instances` / `plex_scope` round-trip via
  `save_config` / `load_config`.
- **Runtime:** "empty = all libraries" shared helper; `unmatched_assets`
  collection-filtering parity before/after migration on a realistic config.
- **CI parity:** backend `ruff check .` + `python3 -m pytest`; frontend
  `npm run lint`, `npx prettier --check src`, `npx stylelint 'src/**/*.css'`.

## Out of scope (YAGNI)

- No curated/stored library list and no reconciliation UI (Plex is truth).
- No change to ARR instance semantics.
- Relational modules (`nestarr`, `labelarr`) are not reshaped.
- No new caching infrastructure beyond a minimal TTL over the existing endpoint.

## Open items for the implementation plan

- Pin the catalog cache mechanism (in-memory TTL vs small cache table vs
  debounced frontend fetch) and its invalidation on instance edit / manual
  refresh.
- Exact shared-helper location for the "empty = all libraries" resolution.
- No Plex entry previously configured → unchanged (module ignores Plex); the
  migrator never invents a Plex entry.
- **Encoding for "selected for upload, no collections" (option 1):** how
  poster/asset `PlexScope` represents an entry that uploads (`add_posters`) but
  matches no collections, given `empty library_names = all`. Candidates: a
  per-entry `match_collections: bool`, or a distinct empty-vs-explicit marker.
  Must round-trip through the shared widget and survive re-save.

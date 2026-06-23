# Plex Library Catalog — Frontend (Plan 2) + Cleanup (Plan 3)

> **For agentic workers:** execute task-by-task; frontend has no unit tests, so verify each task with `npm --prefix frontend run lint`, `cd frontend && npx prettier --check src`, `npx stylelint 'src/**/*.css'`, and `npm --prefix frontend run build`. Commit per task.

**Goal:** Make the UI emit the new split `instances` (ARR) + `plex_scope` shape via a shared catalog-driven Plex picker, surface the libraries catalog on the Settings→Instances Plex card, then remove the transitional backend validator.

**Branch:** `feature/plex-library-catalog`. Backend (Plan 1) already done on this branch.

**Architecture facts (from exploration):**
- Form is strictly one-field = one-config-key (`ModuleSettingsPage.jsx:150-158, 385-390`). → Plex needs its OWN field `plex_scope`, separate from ARR `instances`.
- Only `poster_renamerr` (settings_schema ~316) and `asset_renamerr` (~519) mix Plex+ARR in `instances` today. `unmatched_assets` (~1415) is ARR-only and needs a `plex_scope` field added.
- `InstancesField.jsx` `buildPlexItem` (676-684) emits the old config-dict shape; `PlexInstanceSelector` (578+) already renders per-instance library multiselect + add_posters toggle.
- Per-instance libraries fetched via `instancesAPI.fetchPlexLibraries(name)` → `GET /api/plex/{instance}/libraries` (`instances.js:208`). New catalog endpoint `GET /api/plex/libraries` exists (Plan 1) but is unused by the frontend.
- `InstanceCard.jsx` accepts `plexLibraries` prop but does not render it; `onFetchLibraries` plumbing exists (`InstancesPage.jsx:58-66, 592`).
- `frontend/scripts/check-field-types.js` validates field `type`s in settings_schema — a new `type: 'plex_scope'` must be registered there or lint fails.

---

## Field design (`plex_scope`)

A new field `type: 'plex_scope'`, rendered by `InstancesField` (extend it, don't fork), bound to config key `plex_scope`:
- Renders ONLY Plex instances (from the catalog).
- Receives/emits `List[{instance, library_names, add_posters, match_collections}]`.
- Per Plex instance row: select checkbox → when selected, a library multiselect (catalog libraries; empty = all). Conditional per-row toggles driven by schema flags:
  - `add_posters_option: true` → "Upload posters to this Plex instance" → `add_posters`.
  - `match_collections_option: true` → "Match collections in selected libraries" → `match_collections`.
- Modules:
  - poster_renamerr / asset_renamerr `plex_scope`: both options true.
  - unmatched_assets `plex_scope`: both options false (only instance + libraries; backend ignores the flags).

---

## Task P2-1: Catalog API util + InstanceCard "Libraries (catalog)" section

**Files:**
- Modify `frontend/src/utils/api/instances.js` (add `fetchPlexCatalog`)
- Modify `frontend/src/components/instances/InstanceCard.jsx` (render libraries section)
- Modify `frontend/src/pages/settings/InstancesPage.jsx` (pass libraries; optional: use catalog)

- [ ] Add `fetchPlexCatalog()` to `instances.js` calling `GET /api/plex/libraries`, returning `data.libraries` (`{instance: [{title,type}]}`). Mirror the existing `fetchPlexLibraries` style.
- [ ] In `InstanceCard.jsx`: when `serviceType === 'plex'`, render an explicit "Libraries (catalog)" section listing the instance's libraries (title + a small type chip/icon) with a refresh control wired to the existing `onFetchLibraries`. Use the existing `plexLibraries` prop (already passed at `InstancesPage.jsx:592`). Match the card's existing Tailwind classes/section styling (copy from the adjacent stats block). Keep it lazy: show a "Load libraries" affordance if none loaded yet.
- [ ] Verify: `npm --prefix frontend run lint`, `npx prettier --check src` (in frontend), `npm --prefix frontend run build`. Commit: `feat(ui): explicit Libraries catalog section on Plex instance card`.

## Task P2-2: `plex_scope` field render + emit in InstancesField

**Files:** Modify `frontend/src/components/fields/custom/InstancesField.jsx`; Modify `frontend/scripts/check-field-types.js` (register `plex_scope`).

- [ ] Register `plex_scope` as a known field type in `check-field-types.js` (read it first to match its registry format).
- [ ] In `InstancesField.jsx`, support `field.type === 'plex_scope'` (or a prop the renderer passes): render only Plex instances; for each, the catalog-driven library multiselect plus the two conditional toggles (`add_posters_option`, a NEW `match_collections_option`). Source libraries from `fetchPlexCatalog()` once (fall back to per-instance `fetchPlexLibraries` if catalog errors).
- [ ] Emit/parse the `List[PlexScope]` shape: `parsedSelection` must accept `{instance, library_names, add_posters, match_collections}`; the toggle/library handlers must `onChange` an array of those objects (NOT the old `{name:{...}}` dict). Add a `buildPlexScopeItem(instance, libraries, addPosters, matchCollections)` returning the flat object. Selecting an instance with no libraries = `library_names: []` (all).
- [ ] Verify: lint + prettier + build. Commit: `feat(ui): plex_scope field (catalog picker + match_collections)`.

## Task P2-3: settings_schema — split poster/asset, add plex_scope to 3 modules

**Files:** Modify `frontend/src/utils/constants/settings_schema.js`.

- [ ] `poster_renamerr`: change the `instances` field to ARR-only (`instance_types: ['radarr','sonarr','lidarr']`, `valueFormat: 'string'`, drop `add_posters_option`). Add a new field `{ key: 'plex_scope', type: 'plex_scope', section: 'Targets', label: 'Plex libraries', add_posters_option: true, match_collections_option: true, description: '...' }`.
- [ ] `asset_renamerr`: same split (ARR-only `instances` + `plex_scope` with both options true).
- [ ] `unmatched_assets`: keep `instances` ARR-only; add `{ key: 'plex_scope', type: 'plex_scope', label: 'Plex libraries (collections)', add_posters_option: false, match_collections_option: false, description: 'Report unmatched collections from these Plex libraries (empty = all).' }`.
- [ ] Confirm the music/lidarr conditional fields on poster/asset still key off `instances` correctly (they gate on `service_configured: 'lidarr'` against `instances` — Lidarr stays in `instances`, so unaffected).
- [ ] Verify: `npm --prefix frontend run lint` (runs check-field-types), prettier, build. Commit: `feat(ui): split instances/plex_scope in poster/asset/unmatched schema`.

## Task P2-4: Frontend full verification

- [ ] `npm --prefix frontend run lint` && `cd frontend && npx prettier --check src` && `npx stylelint 'src/**/*.css'` && `npm --prefix frontend run build` — all clean.
- [ ] Manual smoke (RECOMMENDED, flag to user): load Settings→each module, confirm ARR checkboxes + Plex library picker render and a save round-trips `instances`+`plex_scope` correctly against the live backend.

## Task P3-1: Remove the transitional before-validator (backend)

**Files:** Modify `backend/util/config.py`; Modify `tests/test_config_plex_scope.py`.

Rationale: the `model_validator(mode="before")` `_coerce_legacy_instances` on the 3 configs was a shim so the OLD frontend's union payloads validated. Now the frontend emits the split shape, and legacy config FILES are still handled by the migrator on load (is_legacy detects dict-in-instances → split before validate). So the API-path shim is no longer needed.

- [ ] Remove the three `_coerce_legacy_instances` `@model_validator(mode="before")` methods from `PosterRenamerrConfig`, `AssetRenamerrConfig`, `UnmatchedAssetsConfig`. KEEP `_split_legacy_instances` — the migrator imports it.
- [ ] Update `tests/test_config_plex_scope.py`: the tests asserting the configs coerce the legacy union at construction (`test_legacy_union_shape_is_coerced_*`, `test_asset_renamerr_legacy_coercion`, `test_split_legacy_*` that go through the model) now belong to the migrator only. Move/replace them: assert the migrator still splits legacy (already covered in test_config_migrator.py) and that the configs now REJECT the union shape (a dict in `instances` raises ValidationError) — locking that the shim is gone.
- [ ] Verify the migrator path still works end-to-end: a legacy config dict → `migrate()` → `ChubConfig.model_validate` succeeds (this is the real upgrade path; test already exists as `test_real_config_split_preserves_effective_scope`).
- [ ] Verify: `cd backend && ruff check .` + `python3 -m pytest`. Commit: `refactor(config): drop transitional plex_scope legacy validator`.

## Task P3-2: Final integration verification (whole feature)

- [ ] Backend: `ruff check .` + full `pytest` green.
- [ ] Frontend: lint + prettier + stylelint + build green.
- [ ] Re-run the real user config (`/Users/dean/Downloads/message (1).txt`) through `migrate()` + `ChubConfig.model_validate` → confirm `plex_scope` output unchanged from Plan 1.
- [ ] Confirm branch invariant readiness (all files shared; no extension files): `git diff main HEAD --name-only`.
- [ ] Report for user merge decision (main → then develop).

---

## Notes / risks
- No frontend unit tests exist; correctness rests on lint + build + manual smoke. Flag the manual smoke as required before merge.
- `check-field-types.js` may enforce per-type required props — read it before adding `plex_scope`.
- Do NOT push or merge until the user approves (per user instruction: finish the whole plan first).

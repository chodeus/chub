# Plex Library Catalog — Backend (Plan 1 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-module `instances: List[Union[str, Dict]]` shape with a clean `instances: List[str]` (ARR) + `plex_scope: List[PlexScope]` split, migrate existing configs, and keep the old frontend working via a transitional validator — all on the backend, with behaviour preserved.

**Architecture:** A shared `PlexScope` model carries Plex selection + per-library scope + `add_posters` (uploaders) + `match_collections` (uploaders). Converted modules (`poster_renamerr`, `asset_renamerr`, `unmatched_assets`) gain `plex_scope`. A `model_validator(mode="before")` on each accepts the legacy Union shape (so the current frontend keeps working until Plan 2). The migrator splits + persists the clean shape on load. Runtime consumption is updated in the two shared seams (`build_instance_map`, `gather_media_and_collections`) plus `unmatched_assets.compute_instance_filters`.

**Tech Stack:** Python 3, Pydantic v2, pytest, ruff. Spec: `docs/superpowers/specs/2026-06-23-plex-library-catalog-design.md`.

**Branch:** `feature/plex-library-catalog` (off `main`). All files are shared → land on `main`, then `git merge main` into `develop` (byte-identical invariant).

**Verification baseline (run after every task):** `cd backend && ruff check .` and `python3 -m pytest` from repo root.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `backend/util/config.py` | `PlexScope` model; `plex_scope` field + legacy `before` validator on the 3 module configs | Modify |
| `backend/util/config_migrator.py` | Split `instances`→`instances`+`plex_scope` for the 3 modules; detection; persist | Modify |
| `backend/util/connector.py` | `build_instance_map` + `gather_media_and_collections` read `plex_scope` + `match_collections` | Modify |
| `backend/modules/unmatched_assets.py` | `compute_instance_filters` reads `plex_scope` | Modify |
| `backend/api/instances.py` | Cached all-instances libraries endpoint (catalog) | Modify |
| `tests/test_config_*.py`, `tests/test_connector_*.py`, `tests/test_unmatched_assets.py`, `tests/test_api_instances*.py` | Coverage | Modify/Create |

---

## Task 1: `PlexScope` model + `plex_scope` fields + legacy `before` validator

**Files:**
- Modify: `backend/util/config.py` (near `InstancesConfig`, `PosterRenamerrConfig`, `AssetRenamerrConfig`, `UnmatchedAssetsConfig`)
- Test: `tests/test_config_plex_scope.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_plex_scope.py
from backend.util.config import (
    PlexScope,
    PosterRenamerrConfig,
    UnmatchedAssetsConfig,
)


def test_plexscope_defaults():
    s = PlexScope(instance="Plex")
    assert s.library_names == []
    assert s.add_posters is False
    assert s.match_collections is False


def test_new_split_shape_validates():
    c = PosterRenamerrConfig(
        instances=["Radarr", "Sonarr"],
        plex_scope=[{"instance": "Plex", "library_names": ["Movies"], "add_posters": True, "match_collections": True}],
    )
    assert c.instances == ["Radarr", "Sonarr"]
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].add_posters is True
    assert c.plex_scope[0].match_collections is True


def test_legacy_union_shape_is_coerced_poster():
    # Old shape: ARR strings + Plex dict in `instances`, no plex_scope.
    c = PosterRenamerrConfig(
        instances=["Radarr", {"Plex": {"library_names": ["Movies"], "add_posters": True}}]
    )
    assert c.instances == ["Radarr"]
    assert len(c.plex_scope) == 1
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].library_names == ["Movies"]
    assert c.plex_scope[0].add_posters is True
    # non-empty old libraries -> collections were matched -> True
    assert c.plex_scope[0].match_collections is True


def test_legacy_union_empty_libraries_sets_match_collections_false():
    c = PosterRenamerrConfig(
        instances=["Radarr", {"Plex": {"library_names": [], "add_posters": True}}]
    )
    assert c.plex_scope[0].match_collections is False
    assert c.plex_scope[0].add_posters is True


def test_legacy_union_shape_is_coerced_unmatched():
    c = UnmatchedAssetsConfig(
        instances=["Radarr", {"Plex": {"library_names": ["Movies"]}}]
    )
    assert c.instances == ["Radarr"]
    assert c.plex_scope[0].instance == "Plex"
    assert c.plex_scope[0].library_names == ["Movies"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config_plex_scope.py -q`
Expected: FAIL (`PlexScope` import error / `plex_scope` not a field).

- [ ] **Step 3: Add the `PlexScope` model**

Add immediately after `InstanceDetail` in `backend/util/config.py`:

```python
class PlexScope(BaseModel):
    """A module's opt-in selection of a Plex instance + libraries.

    `library_names` empty == all libraries (only meaningful when collections
    are matched). `add_posters` and `match_collections` are honored only by
    uploader modules (poster_renamerr / asset_renamerr); unmatched_assets
    ignores both — it always reports collections for a selected instance.
    """

    instance: str
    library_names: List[str] = Field(default_factory=list)
    add_posters: bool = False
    match_collections: bool = False
```

- [ ] **Step 4: Add a reusable legacy-split helper**

Add below `PlexScope` in `backend/util/config.py`:

```python
def _split_legacy_instances(value: Any) -> Any:
    """Coerce the legacy `instances: List[Union[str, Dict]]` shape into the
    split {instances, plex_scope} shape, in a Pydantic `before` validator.

    Shape-based (no registry needed): string entries -> ARR `instances`;
    dict entries `{name: {library_names, add_posters}}` -> `plex_scope`.
    `match_collections` is derived from whether libraries were listed
    (non-empty old libraries == collections were matched). Idempotent: a
    payload already in the new shape (plex_scope present, instances all
    strings) is returned unchanged.
    """
    if not isinstance(value, dict):
        return value
    instances = value.get("instances")
    if not isinstance(instances, list):
        return value
    # Already split: no dict entries to migrate.
    if all(isinstance(i, str) for i in instances):
        return value

    arr: List[str] = []
    scopes: List[dict] = list(value.get("plex_scope") or [])
    for item in instances:
        if isinstance(item, str):
            arr.append(item)
        elif isinstance(item, dict) and item:
            name = next(iter(item))
            body = item[name] if isinstance(item[name], dict) else {}
            libs = body.get("library_names") or []
            scopes.append(
                {
                    "instance": name,
                    "library_names": libs,
                    "add_posters": bool(body.get("add_posters", False)),
                    "match_collections": bool(libs),
                }
            )
        # Anything else is dropped (matches legacy tolerance).
    new = dict(value)
    new["instances"] = arr
    new["plex_scope"] = scopes
    return new
```

- [ ] **Step 5: Add `plex_scope` + the `before` validator to the three module configs**

In `PosterRenamerrConfig`, replace the `instances` field:

```python
    # ARR instances (radarr/sonarr/lidarr). Plex selection lives in plex_scope.
    instances: List[str] = Field(default_factory=list)
    plex_scope: List[PlexScope] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_instances(cls, value: Any) -> Any:
        return _split_legacy_instances(value)
```

Remove the now-unused `PosterRenamerrPlexInstance` class **only if** nothing else references it (grep first); otherwise leave it. Apply the identical `instances` + `plex_scope` + `_coerce_legacy_instances` block to `AssetRenamerrConfig` and `UnmatchedAssetsConfig` (drop their `Union[...]` `instances` and, for asset, the `AssetRenamerrPlexInstance` ref if unused). Ensure `model_validator` and `Any` are imported (they are already used elsewhere in this file — verify the import line).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config_plex_scope.py -q`
Expected: PASS (all 5).

- [ ] **Step 7: Full baseline + commit**

Run: `cd backend && ruff check . && cd .. && python3 -m pytest -q`
Expected: PASS (existing suite still green — the legacy validator keeps old shapes valid).

```bash
git add backend/util/config.py tests/test_config_plex_scope.py
git commit -m "feat(config): add PlexScope model + plex_scope split with legacy coercion"
```

---

## Task 2: Migrator — split + persist the clean shape

**Files:**
- Modify: `backend/util/config_migrator.py`
- Test: `tests/test_config_migrator.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_config_migrator.py
def test_split_poster_renamerr_instances_to_plex_scope():
    raw = {
        "main": {"theme": "dark"},  # forces migration
        "poster_renamerr": {
            "instances": ["Radarr", {"Plex": {"library_names": ["Movies"], "add_posters": True}}]
        },
    }
    out, notes = migrate(raw)
    assert out["poster_renamerr"]["instances"] == ["Radarr"]
    assert out["poster_renamerr"]["plex_scope"] == [
        {"instance": "Plex", "library_names": ["Movies"], "add_posters": True, "match_collections": True}
    ]
    assert any("plex_scope" in n.rule for n in notes)


def test_split_poster_renamerr_empty_libs_preserves_no_collections():
    raw = {
        "main": {"theme": "dark"},
        "poster_renamerr": {
            "instances": ["Radarr", {"Plex": {"library_names": [], "add_posters": True}}]
        },
    }
    out, _ = migrate(raw)
    scope = out["poster_renamerr"]["plex_scope"][0]
    assert scope["match_collections"] is False
    assert scope["add_posters"] is True


def test_split_unmatched_instances_to_plex_scope():
    raw = {
        "main": {"theme": "dark"},
        "unmatched_assets": {
            "instances": ["Radarr", {"Plex": {"library_names": ["Movies", "Anime"]}}]
        },
    }
    out, _ = migrate(raw)
    assert out["unmatched_assets"]["instances"] == ["Radarr"]
    assert out["unmatched_assets"]["plex_scope"] == [
        {"instance": "Plex", "library_names": ["Movies", "Anime"], "add_posters": False, "match_collections": True}
    ]


def test_split_is_idempotent_on_new_shape():
    raw = {
        "poster_renamerr": {
            "instances": ["Radarr"],
            "plex_scope": [{"instance": "Plex", "library_names": ["Movies"], "add_posters": True, "match_collections": True}],
        }
    }
    assert is_legacy_config(raw) is False
    out, notes = migrate(raw)
    assert out["poster_renamerr"]["plex_scope"] == raw["poster_renamerr"]["plex_scope"]
    assert not any("plex_scope" in n.rule for n in notes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config_migrator.py -q -k "plex_scope or split_"`
Expected: FAIL (no split rule yet; `plex_scope` absent).

- [ ] **Step 3: Add the split rule + detection**

In `backend/util/config_migrator.py`, add a rule (reusing the shape-based logic — keep it consistent with `config._split_legacy_instances`):

```python
_SPLIT_MODULES = ("poster_renamerr", "asset_renamerr", "unmatched_assets")


def _rule_split_instances_to_plex_scope(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """Split legacy `instances: List[Union[str, Dict]]` into
    `instances` (ARR strings) + `plex_scope` for the converted modules.
    Idempotent: a module whose `instances` is already all-strings is skipped.
    """
    for module in _SPLIT_MODULES:
        sec = raw.get(module)
        if not isinstance(sec, dict):
            continue
        instances = sec.get("instances")
        if not isinstance(instances, list):
            continue
        if all(isinstance(i, str) for i in instances):
            continue  # already split / no Plex dicts

        arr: List[str] = []
        scopes: List[dict] = list(sec.get("plex_scope") or [])
        for item in instances:
            if isinstance(item, str):
                arr.append(item)
            elif isinstance(item, dict) and item:
                name = next(iter(item))
                body = item[name] if isinstance(item[name], dict) else {}
                libs = body.get("library_names") or []
                scopes.append(
                    {
                        "instance": name,
                        "library_names": libs,
                        "add_posters": bool(body.get("add_posters", False)),
                        "match_collections": bool(libs),
                    }
                )
        sec["instances"] = arr
        sec["plex_scope"] = scopes
        notes.append(
            MigrationNote(
                rule=f"split:{module}.instances->plex_scope",
                message=(
                    f"Split `{module}.instances` into ARR `instances` and "
                    f"`plex_scope` ({len(scopes)} Plex entr"
                    f"{'y' if len(scopes) == 1 else 'ies'})."
                ),
            )
        )
```

Add to `is_legacy_config` (a non-string entry in any converted module's `instances` is now a legacy signal — this re-introduces, for all three modules, what Fix A removed for unmatched, but now pointing at the split):

```python
    for module in ("poster_renamerr", "asset_renamerr", "unmatched_assets"):
        mod_instances = raw.get(module, {}).get("instances")
        if isinstance(mod_instances, list) and any(
            not isinstance(i, str) for i in mod_instances
        ):
            return True
```

Update the Fix A comment block in `is_legacy_config` (the "deliberately NOT a legacy signal" note for `unmatched_assets`) — it is now superseded; replace it with a pointer to the split detection above.

Call the rule from `migrate()` in the "Shape conversions" group, **before** the cleanar flatten/split lines:

```python
    _rule_split_instances_to_plex_scope(out, notes)
```

- [ ] **Step 4: Rework the Fix A "preserved in place" tests**

In `tests/test_config_migrator.py`, the Fix A tests assert the unmatched dict form is preserved in `instances`. Update them to assert it now migrates into `plex_scope`:

```python
def test_unmatched_dict_form_migrates_into_plex_scope():
    raw = {
        "main": {"theme": "dark"},
        "unmatched_assets": {"instances": ["radarr", "sonarr", {"Plex": {"library_names": ["Movies"]}}]},
    }
    out, notes = migrate(raw)
    assert out["unmatched_assets"]["instances"] == ["radarr", "sonarr"]
    assert out["unmatched_assets"]["plex_scope"][0]["instance"] == "Plex"
    assert any("plex_scope" in n.rule for n in notes)
```

Delete `test_unmatched_instances_dict_form_is_preserved` and update `test_detection_unmatched_instances_dict_entry_is_chub_native` to assert it is now legacy (returns `True`), renaming to `test_detection_unmatched_instances_dict_entry_triggers_split`. Update the end-to-end `_legacy_blob` assertions: `unmatched_assets` should now expose `plex_scope` (not a dict inside `instances`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config_migrator.py -q`
Expected: PASS.

- [ ] **Step 6: Full baseline + commit**

Run: `cd backend && ruff check . && cd .. && python3 -m pytest -q`
Expected: PASS.

```bash
git add backend/util/config_migrator.py tests/test_config_migrator.py
git commit -m "feat(config): migrator splits module instances into instances + plex_scope"
```

---

## Task 3: Runtime — `build_instance_map` + `gather_media_and_collections`

**Files:**
- Modify: `backend/util/connector.py` (`build_instance_map` ~L1231, `gather_media_and_collections` ~L1206)
- Test: `tests/test_connector_plex_scope.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_plex_scope.py
from backend.util.connector import build_instance_map
from backend.util.config import PosterRenamerrConfig


def test_build_instance_map_from_plex_scope():
    cfg = PosterRenamerrConfig(
        instances=["Radarr", "Sonarr"],
        plex_scope=[{"instance": "Plex", "library_names": ["Movies"], "match_collections": True}],
    )
    m = build_instance_map(cfg)
    assert sorted(m["arrs"]) == ["Radarr", "Sonarr"]
    assert m["plex"] == {"Plex": ["Movies"]}


def test_build_instance_map_empty_libraries_is_all():
    cfg = PosterRenamerrConfig(
        instances=[],
        plex_scope=[{"instance": "Plex", "library_names": [], "match_collections": True}],
    )
    # empty libraries -> all (represented as []), consumed downstream as "all"
    assert build_instance_map(cfg)["plex"] == {"Plex": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_connector_plex_scope.py -q`
Expected: FAIL (`build_instance_map` still reads the Union `instances`).

- [ ] **Step 3: Rewrite `build_instance_map`**

Replace the function body in `backend/util/connector.py`:

```python
def build_instance_map(config: Any) -> Dict[str, Any]:
    """Build {"arrs": [...], "plex": {name: [libraries]}} from the split
    `instances` (ARR strings) + `plex_scope` (Plex) fields. An empty
    `library_names` means all libraries (downstream `_determine_target_libraries`
    treats an empty selection as all)."""
    arrs = [i for i in getattr(config, "instances", []) if isinstance(i, str)]
    plex: Dict[str, list] = {}
    for scope in getattr(config, "plex_scope", []) or []:
        plex[scope.instance] = list(scope.library_names or [])
    return {"arrs": arrs, "plex": plex}
```

- [ ] **Step 4: Rewrite `gather_media_and_collections`**

Replace the function body so collections are pulled from `plex_scope` and gated by `match_collections`; empty libraries = all libraries of that instance (read distinct library names present in the cache for the instance):

```python
def gather_media_and_collections(config: Any, db: ChubDB) -> List[dict]:
    """Collect media (ARR, from media_cache) + collections (Plex, from
    collections_cache) a poster/asset run matches against.

    - ARR instances -> all their media_cache rows.
    - plex_scope entries with match_collections -> their collections;
      empty library_names == all libraries of that instance.
    """
    all_media: List[dict] = []
    for name in getattr(config, "instances", []):
        if isinstance(name, str):
            media = db.media.get_by_instance(name)
            if media:
                all_media.extend(media)
    for scope in getattr(config, "plex_scope", []) or []:
        if not getattr(scope, "match_collections", False):
            continue
        libs = list(scope.library_names or [])
        if not libs:
            libs = db.collection.get_library_names_for_instance(scope.instance)
        for library_name in libs:
            collections = db.collection.get_by_instance_and_library(
                scope.instance, library_name
            )
            if collections:
                all_media.extend(collections)
    return all_media
```

- [ ] **Step 5: Add the `get_library_names_for_instance` cache accessor**

In `backend/util/database/collection_cache.py`, add:

```python
    def get_library_names_for_instance(self, instance_name: str) -> list:
        """Distinct library names present in the cache for an instance."""
        rows = self.execute_query(
            "SELECT DISTINCT library_name FROM collections_cache WHERE instance_name=?",
            (instance_name,),
            fetch_all=True,
        )
        return [r["library_name"] for r in (rows or []) if r["library_name"]]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_connector_plex_scope.py -q`
Expected: PASS.

- [ ] **Step 7: Full baseline + commit**

Run: `cd backend && ruff check . && cd .. && python3 -m pytest -q`
Expected: PASS (existing connector/module tests still green — they now build configs via the split shape or the legacy validator).

```bash
git add backend/util/connector.py backend/util/database/collection_cache.py tests/test_connector_plex_scope.py
git commit -m "feat(connector): consume plex_scope + match_collections for media/collections"
```

---

## Task 4: `unmatched_assets.compute_instance_filters` reads `plex_scope`

**Files:**
- Modify: `backend/modules/unmatched_assets.py` (`compute_instance_filters` ~L37)
- Test: `tests/test_unmatched_assets.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_unmatched_assets.py
from backend.util.config import UnmatchedAssetsConfig
from backend.modules.unmatched_assets import UnmatchedAssets


def test_compute_instance_filters_reads_plex_scope():
    mod = UnmatchedAssets()
    mod.config = UnmatchedAssetsConfig(
        instances=["Radarr"],
        plex_scope=[{"instance": "Plex", "library_names": ["Movies"]}],
    )
    mod.compute_instance_filters()
    assert "Radarr" in mod.allowed_instances
    assert "Plex" in mod.allowed_instances
    assert mod.plex_libraries["Plex"] == {"Movies"}


def test_compute_instance_filters_empty_libraries_means_all():
    mod = UnmatchedAssets()
    mod.config = UnmatchedAssetsConfig(
        instances=[], plex_scope=[{"instance": "Plex", "library_names": []}]
    )
    mod.compute_instance_filters()
    assert "Plex" in mod.allowed_instances
    # empty -> all libraries -> no per-library narrowing recorded
    assert "Plex" not in mod.plex_libraries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_unmatched_assets.py -q -k plex_scope`
Expected: FAIL (still iterates `config.instances` dicts).

- [ ] **Step 3: Rewrite `compute_instance_filters`**

```python
    def compute_instance_filters(self) -> None:
        for name in getattr(self.config, "instances", []):
            if isinstance(name, str):
                self.allowed_instances.add(name)
        for scope in getattr(self.config, "plex_scope", []) or []:
            self.allowed_instances.add(scope.instance)
            libs = set(scope.library_names or [])
            if libs:  # empty == all libraries -> no narrowing
                self.plex_libraries[scope.instance] = libs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_unmatched_assets.py -q -k plex_scope`
Expected: PASS.

- [ ] **Step 5: Full baseline + commit**

Run: `cd backend && ruff check . && cd .. && python3 -m pytest -q`
Expected: PASS.

```bash
git add backend/modules/unmatched_assets.py tests/test_unmatched_assets.py
git commit -m "feat(unmatched): read plex_scope for instance/library filtering"
```

---

## Task 5: Cached catalog endpoint (all instances' libraries)

**Files:**
- Modify: `backend/api/instances.py` (add a cached all-instances libraries endpoint near `get_plex_libraries` ~L506)
- Test: `tests/test_api_instances_catalog.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_instances_catalog.py
from backend.util.plex_library_cache import get_cached_libraries, _CACHE


def test_cache_returns_fetched_value_and_memoizes():
    _CACHE.clear()
    calls = {"n": 0}

    def fetch(instance):
        calls["n"] += 1
        return [{"title": "Movies", "type": "movie"}]

    a = get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1000.0)
    b = get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1030.0)
    assert a == b == [{"title": "Movies", "type": "movie"}]
    assert calls["n"] == 1  # second call served from cache


def test_cache_expires_after_ttl():
    _CACHE.clear()
    calls = {"n": 0}

    def fetch(instance):
        calls["n"] += 1
        return [{"title": "Movies", "type": "movie"}]

    get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1000.0)
    get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1100.0)  # > ttl
    assert calls["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_api_instances_catalog.py -q`
Expected: FAIL (module `plex_library_cache` missing).

- [ ] **Step 3: Add the TTL cache utility**

```python
# backend/util/plex_library_cache.py
"""In-memory TTL cache for live-discovered Plex library lists (the catalog).

Pure/injectable: `now` and `fetch` are passed in so it is unit-testable and
free of wall-clock calls. Plex remains the source of truth; this only avoids
re-hitting it on every Instances-page / module-picker render."""
from typing import Callable, Dict, List, Tuple

# instance_name -> (expires_at_epoch, libraries)
_CACHE: Dict[str, Tuple[float, List[dict]]] = {}


def get_cached_libraries(
    instance: str,
    fetch: Callable[[str], List[dict]],
    ttl_seconds: float,
    now: float,
) -> List[dict]:
    entry = _CACHE.get(instance)
    if entry and entry[0] > now:
        return entry[1]
    libs = fetch(instance)
    _CACHE[instance] = (now + ttl_seconds, libs)
    return libs


def invalidate(instance: str | None = None) -> None:
    if instance is None:
        _CACHE.clear()
    else:
        _CACHE.pop(instance, None)
```

- [ ] **Step 4: Wire a cached `GET /api/plex/libraries` endpoint**

In `backend/api/instances.py`, add an endpoint that returns `{instance: [libraries]}` for every configured Plex instance, using `get_cached_libraries` with `time.monotonic()` as `now` and a module-level fetch that reuses the existing per-instance discovery logic (extract the `/library/sections` fetch from `get_plex_libraries` into a helper `_fetch_plex_libraries(plex_data)` and call it from both). Call `plex_library_cache.invalidate(instance)` from the instance create/update/delete handlers so edits don't serve stale libraries.

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_api_instances_catalog.py -q`
Expected: PASS.

- [ ] **Step 6: Full baseline + commit**

Run: `cd backend && ruff check . && cd .. && python3 -m pytest -q`
Expected: PASS.

```bash
git add backend/util/plex_library_cache.py backend/api/instances.py tests/test_api_instances_catalog.py
git commit -m "feat(api): cached Plex library catalog endpoint"
```

---

## Task 6: Behaviour-parity guard + final verification

**Files:**
- Test: `tests/test_config_migrator.py` (add a realistic end-to-end parity test)

- [ ] **Step 1: Add a parity test mirroring the real user config**

```python
def test_real_config_split_preserves_effective_scope():
    raw = {
        "main": {"theme": "dark"},
        "poster_renamerr": {
            "instances": ["Movies", "Shows", {"Plex": {"library_names": ["Movies", "Anime", "Shows"], "add_posters": True}}]
        },
        "unmatched_assets": {
            "instances": ["Movies", "Shows", {"Plex": {"library_names": ["Movies", "Anime", "Shows", "Music"]}}]
        },
    }
    out, _ = migrate(raw)
    pr = out["poster_renamerr"]
    assert pr["instances"] == ["Movies", "Shows"]
    assert pr["plex_scope"][0] == {
        "instance": "Plex", "library_names": ["Movies", "Anime", "Shows"],
        "add_posters": True, "match_collections": True,
    }
    ua = out["unmatched_assets"]
    assert ua["plex_scope"][0]["library_names"] == ["Movies", "Anime", "Shows", "Music"]
    # whole migrated config validates
    from backend.util.config import ChubConfig
    ChubConfig.model_validate(out)
```

- [ ] **Step 2: Run + full suite**

Run: `python3 -m pytest tests/test_config_migrator.py -q` then `cd backend && ruff check . && cd .. && python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_config_migrator.py
git commit -m "test(config): end-to-end plex_scope split parity for a real config"
```

- [ ] **Step 4: Merge to develop (branch invariant)**

After the feature branch is reviewed/merged to `main`:

```bash
git checkout develop && git merge main
git diff main develop --name-status | grep -E '^M' | grep -v 'deploy/docker/Dockerfile'   # must be empty
git push origin develop && git checkout main
```

---

## Self-review notes

- **Spec coverage:** PlexScope (Task 1), split fields (1), migrate+persist (2), runtime empty=all + match_collections (3,4), catalog cache (5), parity (6). Frontend widget + Instances "Libraries (catalog)" section + relational-module wiring are **Plan 2**; transitional-validator removal is **Plan 3**.
- **Transition:** the `before` validator (Task 1) keeps the current frontend's Union payloads valid through Plan 1; removed in Plan 3.
- **Type consistency:** `PlexScope.{instance, library_names, add_posters, match_collections}` used identically in config, migrator output dicts, connector, and unmatched.
- **Out of scope here:** `nestarr` / `labelarr` (unchanged shape), `poster_cleanarr` / `plex_maintenance` (instance-only) — they only change in Plan 2 (shared widget), no backend change.
```

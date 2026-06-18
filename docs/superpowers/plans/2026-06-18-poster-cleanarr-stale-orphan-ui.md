# Poster Cleanarr — Stale & Orphan UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "stale duplicate" detection as a first-class Poster Cleanarr capability and surface both stale (per-media pill) and orphan (separate section) Kometa-asset cleanup in the Poster Cleanarr UI, alongside the existing Plex bloat view.

**Architecture:** Stale detection reuses the existing `poster_cleanarr` orphan-pass machinery (same `/kometa/assets` walk, same modes/gates). One new read endpoint (`GET /api/posters/kometa-assets/scan`) walks the assets dir once and returns `{stale: [...keyed by Plex rating_key], orphans: [...]}`; the existing Plex-bloat endpoint is untouched. The cleanup job gains stale toggles. The page makes a second fetch and merges stale onto bundle rows by `rating_key`. Rows show numbered, color-coded pills — **Bloat (red)** and **Stale (amber)** — hidden when 0, decoded by a **legend** at the top. Orphans (which have no media row) render in their **own section**, with their total shown in the legend. Clean mode gains Bloat/Stale/Orphan checkboxes. The SAME `PosterCleanarrConfig` (per-cleaner enable + mode) drives both ad-hoc UI runs and **scheduled** Poster Cleanarr jobs, so all three cleaners run in any mode (report/move/remove) on a schedule.

**Tech Stack:** Python (FastAPI-style router, SQLite via `ChubDB`), React (hand-rolled utility CSS — no Tailwind), pytest, ruff, eslint, prettier.

**Conventions (read before starting):**
- Backend CI = `ruff check .` + `python3 -m pytest` (no black). Local pytest needs `pip install Wand==0.6.13`.
- Frontend: run BOTH `npm --prefix frontend run lint` AND `cd frontend && npx prettier --check src` (lint does not run prettier; CI checks it).
- Frontend utility classes are hand-rolled: an undefined class renders unstyled with no error. Copy classes from proven rows/pills in the same file; new colors go via inline `style={}` objects (like `bloatPill`), not new utility classes.
- This is a **main-branch (public app)** change. Do not couple to any extension; keep shared files byte-identical to develop after merge.
- Detection lives in `poster_cleanarr` so the UI endpoint and the cleanup job share ONE source of truth.

---

## File Structure

**Backend (modify):**
- `backend/modules/poster_cleanarr.py` — add stale detection (`_build_canonical_folder_map`, `_scan_stale_duplicates`, `_execute_stale_mode`, `_run_stale_pass`, module fn `run_stale_duplicates_pass`), wire into `run()`, extend `_build_output`/`_print_report`, add `VALID_STALE_MODES`.
- `backend/util/config.py` — `PosterCleanarrConfig`: add `stale_duplicates_enabled`, `stale_duplicates_mode`.
- `backend/api/posters.py` — add `GET /plex-metadata/kometa-assets-scan`; extend `POST /plex-metadata/cleanup` overrides with stale toggles.

**Frontend (modify):**
- `frontend/src/utils/api/posters.js` — add `scanKometaAssets()`; cleanup body passes stale fields.
- `frontend/src/pages/poster/PosterCleanarrPage.jsx` — `stalePill`, merge stale onto rows, Orphans section, clean-mode checkboxes, detail-scope clarity label.
- `frontend/src/utils/constants/settings_schema.js` — `poster_cleanarr` stale settings.

**Tests (create/modify):**
- `tests/test_poster_cleanarr_duplicates.py` — new; stale detection + execution + safety gates.
- `tests/test_posters_api_kometa_scan.py` — new; endpoint shape + cleanup override parsing.

---

## Task 1: Stale-mode constants

**Files:**
- Modify: `backend/modules/poster_cleanarr.py:50-72` (constants block)

- [ ] **Step 1: Add the constant**

After `VALID_ORPHAN_MODES` (line 51), add:

```python
VALID_STALE_MODES = {"report", "move", "remove"}
```

- [ ] **Step 2: Verify import surface**

Run: `cd backend && python3 -c "from modules.poster_cleanarr import VALID_STALE_MODES; print(sorted(VALID_STALE_MODES))"`
Expected: `['move', 'remove', 'report']`

- [ ] **Step 3: Commit**

```bash
git add backend/modules/poster_cleanarr.py
git commit -m "feat(poster-cleanarr): add VALID_STALE_MODES constant"
```

---

## Task 2: Canonical folder map (DB → {id: canonical folder})

A stale duplicate is an asset folder whose `{tvdb/tmdb}` id matches a live media item but whose name ≠ that item's canonical folder (`media_cache.folder`). This task builds the id→folder lookup, scoped to instances, from the main (season-less) rows.

**Files:**
- Modify: `backend/modules/poster_cleanarr.py` (add method after `_build_library_id_sets`, ~line 891)
- Test: `tests/test_poster_cleanarr_duplicates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_poster_cleanarr_duplicates.py`:

```python
"""Tests for poster_cleanarr stale-duplicate detection — a Kometa asset folder
whose {tvdb/tmdb} id matches a live media item but whose name != the item's
canonical folder (media_cache.folder). Safety: never remove the only copy."""

import os
from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import PosterCleanarr
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _make():
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
    return m


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _seed(db, instance, folder, tvdb=None, tmdb=None, season=None, plex_mapping_id=None):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, folder, tvdb_id, "
        "tmdb_id, season_number, plex_mapping_id, asset_type, matched) "
        "VALUES (?,?,?,?,?,?,?,?,1)",
        (f"{instance}|{folder}|{season}", instance, folder, tvdb, tmdb, season,
         plex_mapping_id, "show"),
    )


def test_canonical_folder_map_keys_by_id(db):
    m = _make()
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)
    _seed(db, "radarr", "Inception (2010) {tmdb-27205}", tmdb=27205)
    # A season row must NOT define the canonical (folder is the same, season set):
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118, season=1)
    cmap = m._build_canonical_folder_map(db, ["sonarr", "radarr"])
    assert cmap[("tvdb", 367118)] == "Dune Prophecy (2024) {tvdb-367118}"
    assert cmap[("tmdb", 27205)] == "Inception (2010) {tmdb-27205}"


def test_canonical_folder_map_respects_instances(db):
    m = _make()
    _seed(db, "sonarr", "Show A (2020) {tvdb-1}", tvdb=1)
    _seed(db, "other", "Show B (2020) {tvdb-2}", tvdb=2)
    cmap = m._build_canonical_folder_map(db, ["sonarr"])
    assert ("tvdb", 1) in cmap
    assert ("tvdb", 2) not in cmap
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/dean/Code/GitHub/chub && python3 -m pytest tests/test_poster_cleanarr_duplicates.py -v`
Expected: FAIL — `AttributeError: 'PosterCleanarr' object has no attribute '_build_canonical_folder_map'`

- [ ] **Step 3: Implement**

Add after `_build_library_id_sets` (~line 891) in `backend/modules/poster_cleanarr.py`:

```python
    def _build_canonical_folder_map(
        self, db: ChubDB, instances: List[str]
    ) -> Dict[Tuple[str, int], str]:
        """Map ('tvdb'|'tmdb', id) -> the media item's canonical folder name
        (media_cache.folder), scoped to `instances`. Only main (season-less)
        rows define the folder, so the show-level folder isn't shadowed by a
        season row. Used to tell a stale-duplicate asset folder (wrong name)
        from the canonical one."""
        wanted = set(instances)
        out: Dict[Tuple[str, int], str] = {}
        for row in db.media.get_all():
            if row.get("instance_name") not in wanted:
                continue
            if row.get("season_number") is not None:
                continue
            folder = row.get("folder")
            if not folder:
                continue
            for kind, raw in (("tvdb", row.get("tvdb_id")), ("tmdb", row.get("tmdb_id"))):
                try:
                    if raw not in (None, "", 0):
                        out[(kind, int(raw))] = folder
                except (ValueError, TypeError):
                    continue
        return out
```

Ensure `Tuple` is imported (the file already imports from `typing` at line 9: `from typing import Any, Dict, List, Optional, Set, Tuple`).

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/poster_cleanarr.py tests/test_poster_cleanarr_duplicates.py
git commit -m "feat(poster-cleanarr): build canonical-folder map for stale detection"
```

---

## Task 3: Scan for stale-duplicate folders

Walk each asset dir's top-level folders; for any whose `{tvdb/tmdb}` id maps to a live canonical folder but whose own name differs, emit a stale entry. Records whether the canonical-named folder is present on disk (removal-safety gate).

**Files:**
- Modify: `backend/modules/poster_cleanarr.py` (add after `_build_canonical_folder_map`)
- Test: `tests/test_poster_cleanarr_duplicates.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_poster_cleanarr_duplicates.py`:

```python
def test_scan_stale_flags_wrong_named_folder(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    (old / "Season01.jpg").write_bytes(b"yy")
    cmap = {("tvdb", 367118): "Dune Prophecy (2024) {tvdb-367118}"}
    stale = m._scan_stale_duplicates([str(root)], cmap)
    assert len(stale) == 1
    e = stale[0]
    assert e["folder"] == str(old)
    assert e["name"] == "Dune - Prophecy (2024) {tvdb-367118}"
    assert e["canonical"] == "Dune Prophecy (2024) {tvdb-367118}"
    assert e["canonical_present"] is False
    assert e["size"] == 3
    assert e["id"] == ("tvdb", 367118)


def test_scan_stale_skips_canonical_folder(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    good = root / "Dune Prophecy (2024) {tvdb-367118}"
    good.mkdir(parents=True)
    (good / "poster.jpg").write_bytes(b"x")
    cmap = {("tvdb", 367118): "Dune Prophecy (2024) {tvdb-367118}"}
    assert m._scan_stale_duplicates([str(root)], cmap) == []


def test_scan_stale_ignores_unknown_id(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    folder = root / "Some Show (2020) {tvdb-999}"
    folder.mkdir(parents=True)
    (folder / "poster.jpg").write_bytes(b"x")
    assert m._scan_stale_duplicates([str(root)], {("tvdb", 1): "X"}) == []


def test_scan_stale_marks_canonical_present(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    (root / "Dune Prophecy (2024) {tvdb-367118}").mkdir(parents=True)
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    cmap = {("tvdb", 367118): "Dune Prophecy (2024) {tvdb-367118}"}
    stale = m._scan_stale_duplicates([str(root)], cmap)
    assert len(stale) == 1
    assert stale[0]["canonical_present"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -k scan_stale -v`
Expected: FAIL — no attribute `_scan_stale_duplicates`

- [ ] **Step 3: Implement**

Add after `_build_canonical_folder_map`. Reuse `tmdb_id_regex` / `tvdb_id_regex` (already imported at line 14):

```python
    def _scan_stale_duplicates(
        self,
        asset_dirs: List[str],
        canonical_by_id: Dict[Tuple[str, int], str],
    ) -> List[Dict[str, Any]]:
        """Top-level asset folders whose {tvdb/tmdb} id matches a live media
        item but whose name != that item's canonical folder. Spare-only on the
        id: an id with no live match is left to the orphan pass, never flagged
        here. `canonical_present` records whether the correctly-named folder is
        already on disk — removal must keep the only copy (see
        _execute_stale_mode)."""
        out: List[Dict[str, Any]] = []
        for asset_dir in asset_dirs:
            if not os.path.isdir(asset_dir):
                continue
            try:
                entries = sorted(os.listdir(asset_dir))
            except OSError:
                continue
            for name in entries:
                full = os.path.join(asset_dir, name)
                if not os.path.isdir(full):
                    continue
                canonical = None
                ident = None
                mt = tmdb_id_regex.search(name)
                mv = tvdb_id_regex.search(name)
                if mv and ("tvdb", int(mv.group(1))) in canonical_by_id:
                    ident = ("tvdb", int(mv.group(1)))
                elif mt and ("tmdb", int(mt.group(1))) in canonical_by_id:
                    ident = ("tmdb", int(mt.group(1)))
                if ident is None:
                    continue  # no live id match -> orphan-pass territory, not stale
                canonical = canonical_by_id[ident]
                if name == canonical:
                    continue  # this IS the canonical folder
                size = 0
                for r, _d, files in os.walk(full):
                    for f in files:
                        try:
                            size += os.path.getsize(os.path.join(r, f))
                        except OSError:
                            pass
                out.append(
                    {
                        "folder": full,
                        "asset_dir": asset_dir,
                        "name": name,
                        "canonical": canonical,
                        "canonical_present": os.path.isdir(
                            os.path.join(asset_dir, canonical)
                        ),
                        "id": ident,
                        "size": size,
                    }
                )
        return out
```

NOTE: `tmdb_id_regex`/`tvdb_id_regex` match the `{tmdb-N}`/`{tvdb-N}` content. Confirm they capture the digits in group(1) — they are the same regexes the orphan pass uses for id sparing (`_first_int_id(tmdb_id_regex, names)`), so behavior is consistent. If `.search().group(1)` is not the integer, mirror the orphan pass's `_first_int_id` helper instead.

- [ ] **Step 4: Verify regex group**

Run: `cd backend && python3 -c "from util.constants import tvdb_id_regex; m=tvdb_id_regex.search('X {tvdb-367118}'); print(m.group(1) if m else None)"`
Expected: prints `367118`. If it prints something else or `None`, adjust the implementation to use the orphan pass's `_first_int_id(regex, (name,))` instead of `.search().group(1)` and re-run.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -k scan_stale -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/modules/poster_cleanarr.py tests/test_poster_cleanarr_duplicates.py
git commit -m "feat(poster-cleanarr): scan for stale-duplicate asset folders"
```

---

## Task 4: Execute stale mode (report/move/remove) with keep-only-copy safety

**Files:**
- Modify: `backend/modules/poster_cleanarr.py` (add after `_scan_stale_duplicates`; reuse `ORPHAN_RESTORE_DIR_NAME`, `shutil`, `_clean_empty_dirs`)
- Test: `tests/test_poster_cleanarr_duplicates.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def _cfg(m, mode="remove"):
    m.config = SimpleNamespace()
    return m


def test_execute_stale_remove_deletes_old_folder(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    (root / "Dune Prophecy (2024) {tvdb-1}").mkdir(parents=True)  # canonical present
    old = root / "Dune - Prophecy (2024) {tvdb-1}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [{
        "folder": str(old), "asset_dir": str(root),
        "name": old.name, "canonical": "Dune Prophecy (2024) {tvdb-1}",
        "canonical_present": True, "id": ("tvdb", 1), "size": 1,
    }]
    res = m._execute_stale_mode(stale, "remove")
    assert res["count"] == 1
    assert not old.exists()


def test_execute_stale_remove_keeps_only_copy(tmp_path):
    """If the canonical folder is NOT on disk yet, removing the stale dup would
    delete the only staged copy — keep it and report instead."""
    m = _make()
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-1}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [{
        "folder": str(old), "asset_dir": str(root),
        "name": old.name, "canonical": "Dune Prophecy (2024) {tvdb-1}",
        "canonical_present": False, "id": ("tvdb", 1), "size": 1,
    }]
    res = m._execute_stale_mode(stale, "remove")
    assert res["count"] == 0  # nothing removed
    assert old.exists()       # only copy preserved


def test_execute_stale_report_deletes_nothing(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-1}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [{
        "folder": str(old), "asset_dir": str(root), "name": old.name,
        "canonical": "Dune Prophecy (2024) {tvdb-1}", "canonical_present": True,
        "id": ("tvdb", 1), "size": 1,
    }]
    res = m._execute_stale_mode(stale, "report")
    assert res["count"] == 1
    assert old.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -k execute_stale -v`
Expected: FAIL — no attribute `_execute_stale_mode`

- [ ] **Step 3: Implement**

```python
    def _execute_stale_mode(
        self, dupes: List[Dict[str, Any]], mode: str
    ) -> Dict[str, Any]:
        """report/move/remove stale-duplicate FOLDERS. move/remove are skipped
        for an entry whose canonical folder is not yet on disk so the only
        staged copy is never destroyed (the renamer recreates the canonical
        folder on its next run, after which this dup is safe to drop)."""
        count = 0
        total_size = 0
        touched: Set[str] = set()
        for d in dupes:
            folder = d["folder"]
            size = d.get("size", 0)
            if mode == "report":
                self.logger.info(
                    f"  [STALE DUP] {folder} (current: {d['canonical']})"
                )
                count += 1
                total_size += size
                continue
            if not d.get("canonical_present"):
                self.logger.info(
                    f"  [STALE KEPT] {folder} — canonical '{d['canonical']}' "
                    "not staged yet; keeping the only copy"
                )
                continue
            if mode == "move":
                dest_root = os.path.join(d["asset_dir"], ORPHAN_RESTORE_DIR_NAME)
                dest = os.path.join(dest_root, d["name"])
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(folder, dest)
                    self.logger.info(f"  [STALE MOVED] {folder} -> {dest}")
                    count += 1
                    total_size += size
                    touched.add(d["asset_dir"])
                except OSError as e:
                    self.logger.error(f"Failed to move {folder}: {e}")
            elif mode == "remove":
                try:
                    shutil.rmtree(folder)
                    self.logger.info(f"  [STALE REMOVED] {folder}")
                    count += 1
                    total_size += size
                    touched.add(d["asset_dir"])
                except OSError as e:
                    self.logger.error(f"Failed to remove {folder}: {e}")
        empty = sum(self._clean_empty_dirs(d) for d in touched)
        self.logger.info(
            f"   → stale duplicates: {count} {mode}d"
            + (f", {empty} empty dir(s) pruned" if empty else "")
        )
        return {"count": count, "total_size": total_size, "mode": mode}
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -k execute_stale -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/poster_cleanarr.py tests/test_poster_cleanarr_duplicates.py
git commit -m "feat(poster-cleanarr): execute stale-duplicate report/move/remove safely"
```

---

## Task 5: Orchestrating pass + module-level entry + run() wiring

**Files:**
- Modify: `backend/modules/poster_cleanarr.py` — add `_run_stale_pass`, module fn `run_stale_duplicates_pass` (near `run_orphan_assets_pass`, ~1191), and a block in `run()` after the orphan block (line 223).
- Test: `tests/test_poster_cleanarr_duplicates.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_run_stale_pass_aborts_when_no_instances(db, tmp_path):
    m = _make()
    res = m._run_stale_pass(db=db, instances=[], asset_dirs=[str(tmp_path)],
                            mode="report", logger=_logger())
    assert res["count"] == 0


def test_run_stale_pass_reports(db, tmp_path):
    m = _make()
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    res = m._run_stale_pass(db=db, instances=["sonarr"], asset_dirs=[str(root)],
                            mode="report", logger=_logger())
    assert res["count"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -k run_stale -v`
Expected: FAIL — no attribute `_run_stale_pass`

- [ ] **Step 3: Implement the pass**

Add after `_execute_stale_mode`:

```python
    def _run_stale_pass(
        self,
        db: ChubDB,
        instances: List[str],
        asset_dirs: List[str],
        mode: str,
        logger: Logger,
    ) -> Dict[str, Any]:
        """Detect + act on stale-duplicate asset folders. Mirrors
        _run_orphan_pass's guards: invalid mode / empty asset_dirs / no
        instances all abort to a no-op."""
        if mode not in VALID_STALE_MODES:
            logger.error(
                f"Invalid stale_duplicates_mode '{mode}'. "
                f"Must be one of: {', '.join(sorted(VALID_STALE_MODES))}"
            )
            return {"count": 0, "total_size": 0, "mode": mode}
        valid_dirs = [d for d in asset_dirs if os.path.isdir(d)]
        if not valid_dirs:
            return {"count": 0, "total_size": 0, "mode": mode}
        if not instances:
            logger.error(
                "Stale-duplicate cleanup enabled but no instances selected."
            )
            return {"count": 0, "total_size": 0, "mode": mode}
        canonical = self._build_canonical_folder_map(db, instances)
        if not canonical:
            logger.warning(
                "No canonical folders for the configured instances — run "
                "poster_renamerr to populate media_cache before stale cleanup."
            )
            return {"count": 0, "total_size": 0, "mode": mode}
        dupes = self._scan_stale_duplicates(valid_dirs, canonical)
        total = sum(d["size"] for d in dupes)
        logger.info(
            f"Found {len(dupes)} stale-duplicate folder(s) ({format_bytes(total)})."
        )
        return self._execute_stale_mode(dupes, mode)
```

- [ ] **Step 4: Implement the module-level entry**

Add right after `run_orphan_assets_pass` (~line 1215):

```python
def run_stale_duplicates_pass(
    db: ChubDB,
    instances: List[str],
    asset_dirs: List[str],
    mode: str,
    logger: Logger,
) -> Dict[str, Any]:
    """Shared entry point so poster_renamerr (or any future caller) can run the
    stale-duplicate pass without a full PosterCleanarr instance."""
    cleanarr = PosterCleanarr.__new__(PosterCleanarr)
    cleanarr.logger = logger
    return cleanarr._run_stale_pass(
        db=db, instances=instances, asset_dirs=asset_dirs, mode=mode, logger=logger
    )
```

- [ ] **Step 5: Wire into `run()`**

In `backend/modules/poster_cleanarr.py`, immediately after the orphan block that ends at line 223 (the `)` closing `_run_orphan_pass(...)`), and before the `# === Clean empty directories ===` comment, insert:

```python
            # === Stale-duplicate asset cleanup ===
            stale_stats: Dict[str, Any] = {"count": 0, "total_size": 0}
            if getattr(self.config, "stale_duplicates_enabled", False):
                with ChubDB(logger=self.logger) as db:
                    stale_stats = self._run_stale_pass(
                        db=db,
                        instances=self._resolve_orphan_instances(self.config),
                        asset_dirs=list(getattr(self.config, "asset_dirs", []) or []),
                        mode=getattr(self.config, "stale_duplicates_mode", "report"),
                        logger=self.logger,
                    )
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py -v`
Expected: PASS (all tasks-2-5 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/modules/poster_cleanarr.py tests/test_poster_cleanarr_duplicates.py
git commit -m "feat(poster-cleanarr): orchestrate stale-duplicate pass + run() wiring"
```

---

## Task 6: Report row + notification for stale stats

`run()` currently builds output from `(bloat_stats, orphan_stats, empty_dirs, elapsed)`. Thread `stale_stats` through so it appears in the summary and notification.

**Files:**
- Modify: `backend/modules/poster_cleanarr.py` — `_build_output` (1116-1140), `_print_report` (1142-1188), the `run()` call site (line 232) and `has_activity` (236-238).

- [ ] **Step 1: Update `_build_output` signature + body**

Change `def _build_output(self, bloat_stats, orphan_stats, empty_dirs, elapsed)` to accept `stale_stats` and add to the returned dict:

```python
    def _build_output(
        self,
        bloat_stats: Dict[str, Any],
        orphan_stats: Dict[str, Any],
        stale_stats: Dict[str, Any],
        empty_dirs: int,
        elapsed: float,
    ) -> Dict[str, Any]:
        ...  # existing bloat/orphan keys unchanged
        return {
            "mode": self.mode,
            "bloat": { ... },     # unchanged
            "orphan": { ... },    # unchanged
            "stale": {
                "count": stale_stats.get("count", 0),
                "size": stale_stats.get("total_size", 0),
                "size_human": format_bytes(stale_stats.get("total_size", 0)),
                "mode": stale_stats.get("mode", ""),
            },
            "empty_dirs": empty_dirs,
            "elapsed": round(elapsed, 1),
        }
```

- [ ] **Step 2: Update `_print_report`**

After the orphan summary-row block (ends line 1165), add a mirrored stale block:

```python
        if output["stale"]["count"] > 0 or output["stale"].get("mode"):
            stale_label = MODE_LABELS.get(
                output["stale"].get("mode", "report"), {}
            ).get("ed", "Processed")
            summary_rows.append(
                [
                    f"Stale Duplicates ({stale_label})",
                    str(output["stale"]["count"]),
                    output["stale"]["size_human"],
                ]
            )
```

- [ ] **Step 3: Update `run()` call site + has_activity**

At line 232 change to:

```python
            output = self._build_output(
                bloat_stats, orphan_stats, stale_stats, empty_dirs, elapsed
            )
```

At lines 236-238 change `has_activity` to include stale:

```python
            has_activity = (
                bloat_stats.get("count", 0) > 0
                or orphan_stats.get("count", 0) > 0
                or stale_stats.get("count", 0) > 0
            )
```

- [ ] **Step 4: Guard existing test**

Run: `python3 -m pytest tests/test_poster_cleanarr.py tests/test_poster_cleanarr_orphans.py -v`
Expected: PASS. If any test calls `_build_output(...)` positionally with 4 args, update it to pass `stale_stats={"count":0,"total_size":0}` in the new third position.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/poster_cleanarr.py tests/
git commit -m "feat(poster-cleanarr): surface stale-duplicate stats in report + notification"
```

---

## Task 7: Config fields

**Files:**
- Modify: `backend/util/config.py:562-593` (`PosterCleanarrConfig`)

- [ ] **Step 1: Add fields**

After `orphan_ignore_titles` (line 593) in `PosterCleanarrConfig`:

```python
    # Stale-duplicate cleanup: a Kometa asset folder whose {tvdb/tmdb} id
    # matches a live item but whose name != the item's canonical folder.
    stale_duplicates_enabled: bool = False
    stale_duplicates_mode: str = "report"  # report | move | remove
```

- [ ] **Step 2: Verify load**

Run: `cd backend && python3 -c "from util.config import PosterCleanarrConfig as C; c=C(); print(c.stale_duplicates_enabled, c.stale_duplicates_mode)"`
Expected: `False report`

- [ ] **Step 3: Commit**

```bash
git add backend/util/config.py
git commit -m "feat(config): add poster_cleanarr stale_duplicates settings"
```

---

## Task 8: Scan endpoint `GET /api/posters/kometa-assets-scan`

Walks the assets dir ONCE, returns stale (keyed by resolved Plex rating_key) + orphans. Reuses the same detection methods so UI and job agree.

**Files:**
- Modify: `backend/api/posters.py` — add the route near the other `/plex-metadata/*` routes (after line 3180); reuse `get_cleanarr_logger` (32-40), `PosterCleanarr`, `ChubDB`.
- Test: `tests/test_posters_api_kometa_scan.py`

- [ ] **Step 1: Write the failing test (resolver helper)**

The route resolves each stale entry's `{tvdb/tmdb}` id to a Plex `rating_key` via `media_cache.plex_mapping_id → plex_media_cache.plex_id`. Put that join in a testable module function. Create `tests/test_posters_api_kometa_scan.py`:

```python
from types import SimpleNamespace

from backend.modules.poster_cleanarr import PosterCleanarr
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None, info=lambda *a, **k: None,
        warning=lambda *a, **k: None, error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def test_resolve_rating_keys_via_plex_mapping(tmp_path):
    from backend.api.posters import _stale_rating_key_map
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as db:
        db.media.execute_query(
            "INSERT INTO plex_media_cache (id, plex_id, instance_name) VALUES (?,?,?)",
            (5, "12345", "Chodeus"),
        )
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key, instance_name, tvdb_id, "
            "plex_mapping_id, asset_type, matched) VALUES (?,?,?,?,?,1)",
            ("k", "sonarr", 367118, 5, "show"),
        )
        m = _stale_rating_key_map(db, [("tvdb", 367118)])
        assert m[("tvdb", 367118)] == 12345
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_posters_api_kometa_scan.py -v`
Expected: FAIL — `cannot import name '_stale_rating_key_map'`

- [ ] **Step 3: Implement the resolver**

In `backend/api/posters.py`, add a module-level helper (near the other helpers at the top, after `get_cleanarr_logger`):

```python
def _stale_rating_key_map(db, ids):
    """Map ('tvdb'|'tmdb', id) -> Plex rating_key (int) via
    media_cache.plex_mapping_id -> plex_media_cache.plex_id. Missing mappings
    are simply absent from the result."""
    out = {}
    if not ids:
        return out
    rows = db.media.execute_query(
        "SELECT m.tvdb_id AS tvdb_id, m.tmdb_id AS tmdb_id, p.plex_id AS plex_id "
        "FROM media_cache m JOIN plex_media_cache p ON m.plex_mapping_id = p.id "
        "WHERE m.plex_mapping_id IS NOT NULL",
        fetch=True,
    )
    wanted = set(ids)
    for r in rows or []:
        try:
            pid = int(r["plex_id"])
        except (ValueError, TypeError, KeyError):
            continue
        for kind, raw in (("tvdb", r.get("tvdb_id")), ("tmdb", r.get("tmdb_id"))):
            try:
                key = (kind, int(raw)) if raw not in (None, "", 0) else None
            except (ValueError, TypeError):
                key = None
            if key in wanted:
                out[key] = pid
    return out
```

NOTE: confirm the `db.media.execute_query(..., fetch=True)` signature and row-access style (`r["col"]` vs `r.get`) against an existing query in `backend/util/database/media_cache.py`; match whatever that module uses (it may return `sqlite3.Row` or dict). Adjust `r.get`/`r["..."]` accordingly so the test passes.

- [ ] **Step 4: Run resolver test**

Run: `python3 -m pytest tests/test_posters_api_kometa_scan.py -v`
Expected: PASS

- [ ] **Step 5: Add the route**

In `backend/api/posters.py` after the `variant-thumbnail` route (line 3180):

```python
@router.get("/plex-metadata/kometa-assets-scan")
async def scan_kometa_assets(
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cleanarr_logger),
):
    """Walk the Kometa assets dir once; return stale-duplicate folders (keyed by
    resolved Plex rating_key) and orphan assets. Read-only — never deletes.
    Detection reuses poster_cleanarr so this matches the cleanup job exactly."""
    try:
        from backend.modules.poster_cleanarr import PosterCleanarr
        from backend.util.config import load_config

        cfg = load_config().poster_cleanarr
        instances = PosterCleanarr._resolve_orphan_instances(cfg)
        asset_dirs = list(getattr(cfg, "asset_dirs", []) or [])
        ca = PosterCleanarr.__new__(PosterCleanarr)
        ca.logger = logger

        canonical = ca._build_canonical_folder_map(db, instances)
        stale_raw = ca._scan_stale_duplicates(asset_dirs, canonical)
        rk = _stale_rating_key_map(db, [d["id"] for d in stale_raw])
        stale = [
            {
                "rating_key": rk.get(d["id"]),
                "name": d["name"],
                "canonical": d["canonical"],
                "canonical_present": d["canonical_present"],
                "size": d["size"],
                "folder": d["folder"],
            }
            for d in stale_raw
        ]

        titles = ca._build_library_title_set(db, instances, True)
        tmdb_ids, tvdb_ids = ca._build_library_id_sets(db, instances)
        orphan_raw = (
            ca._scan_orphan_assets(asset_dirs, titles, tmdb_ids, tvdb_ids, set())
            if titles
            else []
        )
        orphans = [
            {"path": o["path"], "parsed": o.get("parsed"), "size": o["size"]}
            for o in orphan_raw
        ]
        return ok(
            "Kometa asset scan complete",
            {
                "stale": stale,
                "orphans": orphans,
                "stats": {
                    "stale_count": len(stale),
                    "orphan_count": len(orphans),
                },
            },
        )
    except Exception as e:
        logger.error(f"Kometa asset scan failed: {e}")
        return error(
            f"Kometa asset scan failed: {str(e)}",
            code="KOMETA_SCAN_ERROR",
            status_code=500,
        )
```

NOTE: `_resolve_orphan_instances` is a `@staticmethod` taking `config` — calling it as `PosterCleanarr._resolve_orphan_instances(cfg)` is correct. Confirm `ok`/`error` helpers are already imported in this file (they are used by neighboring routes).

- [ ] **Step 6: Smoke-test import**

Run: `cd backend && python3 -c "import api.posters"`
Expected: no error.

- [ ] **Step 7: Commit**

```bash
git add backend/api/posters.py tests/test_posters_api_kometa_scan.py
git commit -m "feat(api): add kometa-assets-scan endpoint (stale + orphan, read-only)"
```

---

## Task 9: Extend the cleanup job to accept stale toggles

**Files:**
- Modify: `backend/api/posters.py:2958-3026` (`run_plex_metadata_cleanup`)
- Test: `tests/test_posters_api_kometa_scan.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_posters_api_kometa_scan.py`:

```python
def test_cleanup_overrides_parse_stale():
    from backend.api.posters import _build_cleanup_overrides
    ov = _build_cleanup_overrides({
        "mode": "remove",
        "stale_duplicates_enabled": True,
        "stale_duplicates_mode": "move",
    })
    assert ov["mode"] == "remove"
    assert ov["stale_duplicates_enabled"] is True
    assert ov["stale_duplicates_mode"] == "move"


def test_cleanup_overrides_reject_bad_stale_mode():
    from backend.api.posters import _build_cleanup_overrides
    import pytest
    with pytest.raises(ValueError):
        _build_cleanup_overrides({"mode": "report", "stale_duplicates_mode": "nuke"})
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_posters_api_kometa_scan.py -k overrides -v`
Expected: FAIL — `cannot import name '_build_cleanup_overrides'`

- [ ] **Step 3: Refactor override-building into a testable function**

In `backend/api/posters.py`, extract the override assembly from `run_plex_metadata_cleanup` into a module function and call it from the route. The function raises `ValueError` on bad modes (the route maps that to a 400):

```python
def _build_cleanup_overrides(body: dict) -> dict:
    mode = (body.get("mode") or "report").lower()
    if mode not in ("report", "move", "remove"):
        raise ValueError(f"Invalid mode '{mode}'")
    overrides: dict = {"mode": mode}

    target_paths = body.get("target_paths")
    if isinstance(target_paths, list) and target_paths:
        overrides["target_paths"] = [str(p) for p in target_paths]

    if "orphan_assets_enabled" in body:
        overrides["orphan_assets_enabled"] = bool(body.get("orphan_assets_enabled"))
    orphan_mode = body.get("orphan_assets_mode")
    if isinstance(orphan_mode, str):
        orphan_mode = orphan_mode.lower()
        if orphan_mode not in ("report", "move", "remove"):
            raise ValueError(f"Invalid orphan_assets_mode '{orphan_mode}'")
        overrides["orphan_assets_mode"] = orphan_mode

    if "stale_duplicates_enabled" in body:
        overrides["stale_duplicates_enabled"] = bool(
            body.get("stale_duplicates_enabled")
        )
    stale_mode = body.get("stale_duplicates_mode")
    if isinstance(stale_mode, str):
        stale_mode = stale_mode.lower()
        if stale_mode not in ("report", "move", "remove"):
            raise ValueError(f"Invalid stale_duplicates_mode '{stale_mode}'")
        overrides["stale_duplicates_mode"] = stale_mode

    asset_dirs = body.get("asset_dirs")
    if isinstance(asset_dirs, list):
        overrides["asset_dirs"] = [str(p) for p in asset_dirs]
    return overrides
```

Then in `run_plex_metadata_cleanup`, replace lines 2980-3003 with:

```python
        try:
            overrides = _build_cleanup_overrides(body)
        except ValueError as ve:
            return error(str(ve), code="INVALID_MODE", status_code=400)
        mode = overrides["mode"]
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_posters_api_kometa_scan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/posters.py tests/test_posters_api_kometa_scan.py
git commit -m "feat(api): accept stale-duplicate toggles in cleanup job"
```

---

## Task 10: Frontend API client

**Files:**
- Modify: `frontend/src/utils/api/posters.js` (near `runPlexMetadataCleanup`, line 637)

- [ ] **Step 1: Add `scanKometaAssets`**

After `runPlexMetadataCleanup` (line 637), add:

```javascript
    scanKometaAssets: () =>
        apiCore.get('/posters/plex-metadata/kometa-assets-scan'),
```

(The cleanup body already passes through whatever the page sends, so `runPlexMetadataCleanup` needs no change — the page will include `stale_duplicates_enabled`/`orphan_assets_enabled` in the body it builds.)

- [ ] **Step 2: Lint**

Run: `npm --prefix frontend run lint && cd frontend && npx prettier --check src/utils/api/posters.js`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/api/posters.js
git commit -m "feat(frontend): add scanKometaAssets API client method"
```

---

## Task 11: Numbered Bloat/Stale pills + legend

The existing red bloat pill already shows a number and hides when 0. Add a matching amber **Stale** pill (numbered, hidden when 0) and a **legend** at the top decoding both colors. Orphans are counted in the legend (their list is Task 12); they cannot be a per-row pill because they have no media row.

**Files:**
- Modify: `frontend/src/pages/poster/PosterCleanarrPage.jsx`

- [ ] **Step 1: Add `stalePill` style**

After `bloatPill` (ends line 1333), add:

```javascript
const stalePill = {
    padding: '1px 6px',
    borderRadius: '9999px',
    background: 'rgba(245,158,11,0.2)',
    color: '#f59e0b',
    fontWeight: 600,
    fontSize: '10px',
};
```

- [ ] **Step 2: Fetch the asset scan in the page component**

In the main component, alongside the existing bundle fetch (~line 445), add state + effect:

```javascript
    const [staleByRk, setStaleByRk] = useState(() => new Map());
    const [orphans, setOrphans] = useState([]);

    useEffect(() => {
        let cancelled = false;
        postersAPI
            .scanKometaAssets()
            .then(res => {
                if (cancelled) return;
                const data = res?.data || {};
                const map = new Map();
                for (const s of data.stale || []) {
                    if (s.rating_key == null) continue;
                    map.set(s.rating_key, (map.get(s.rating_key) || 0) + 1);
                }
                setStaleByRk(map);
                setOrphans(data.orphans || []);
            })
            .catch(() => {
                if (!cancelled) {
                    setStaleByRk(new Map());
                    setOrphans([]);
                }
            });
        return () => {
            cancelled = true;
        };
    }, []);
```

- [ ] **Step 3: Pass `staleCount` into `BundleTreeRow` and render the pill**

Where `<BundleTreeRow ... />` is rendered (~line 959), add prop `staleCount={staleByRk.get(bundle.rating_key) || 0}`.

In `BundleTreeRow`'s props (line 1344-1353) add `staleCount`, and after the bloat pill (line 1393) add:

```javascript
                        {staleCount > 0 && (
                            <span style={stalePill} title="Stale duplicate asset folder">
                                ⧉ {staleCount}
                            </span>
                        )}
```

- [ ] **Step 4: Add the legend at the top**

Next to the library stats line (the `{stats.bundle_count} items · … bloat …` block around line 806-808), add a legend decoding the pills. Hide the orphan entry when there are none:

```javascript
                    <div className="flex items-center gap-3 text-xs text-tertiary mt-1">
                        <span className="flex items-center gap-1">
                            <span style={bloatPill}>●</span> bloat
                        </span>
                        <span className="flex items-center gap-1">
                            <span style={stalePill}>⧉</span> stale duplicate
                        </span>
                        {orphans.length > 0 && (
                            <span>orphaned assets: {orphans.length} (see below)</span>
                        )}
                    </div>
```

- [ ] **Step 5: Verify in the browser (preview)**

Start the dev server, log in, open Poster Cleanarr, confirm: amber numbered stale pills appear on rows with stale dupes and are ABSENT when 0; the red bloat pill is unchanged; the legend decodes both colors. (See the verification workflow in the final task.)

- [ ] **Step 6: Lint + commit**

```bash
npm --prefix frontend run lint && cd frontend && npx prettier --check src
git add frontend/src/pages/poster/PosterCleanarrPage.jsx
git commit -m "feat(frontend): numbered stale pill + pill legend on Poster Cleanarr"
```

---

## Task 12: Orphans section

**Files:**
- Modify: `frontend/src/pages/poster/PosterCleanarrPage.jsx`

- [ ] **Step 1: Render an Orphans panel below the master-detail grid**

After the `<section>` that holds the bloat master-detail grid (the element closed near line 1128 in the original; locate the matching `</section>` for the grid you bounded earlier), add a sibling block (copy spacing/border classes from the grid's `<section className="rounded-lg border border-border overflow-hidden bg-surface">`):

```javascript
                {orphans.length > 0 && (
                    <section className="rounded-lg border border-border bg-surface mt-4 p-4">
                        <div className="flex items-center gap-2 mb-3">
                            <h2 className="text-sm font-semibold text-primary">
                                Orphaned assets
                            </h2>
                            <span style={typeBadge}>{orphans.length}</span>
                            <span className="text-tertiary text-xs">
                                Kometa assets with no matching media in your library
                            </span>
                        </div>
                        <div className="overflow-y-auto" style={{ maxHeight: '320px' }}>
                            {orphans.map(o => (
                                <div
                                    key={o.path}
                                    className="flex items-center justify-between gap-2 py-1.5 border-b border-border text-sm"
                                >
                                    <span className="truncate text-secondary">
                                        {o.path}
                                    </span>
                                    <span className="text-tertiary text-xs whitespace-nowrap">
                                        {formatBytes(o.size)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </section>
                )}
```

Confirm `formatBytes` and `typeBadge` are in scope (both already used in this file).

- [ ] **Step 2: Verify in browser** — orphan list appears only when non-empty; scrolls internally.

- [ ] **Step 3: Lint + commit**

```bash
npm --prefix frontend run lint && cd frontend && npx prettier --check src
git add frontend/src/pages/poster/PosterCleanarrPage.jsx
git commit -m "feat(frontend): add Orphaned assets section to Poster Cleanarr"
```

---

## Task 13: Clean-mode checkboxes (Bloat / Stale / Orphan)

**Files:**
- Modify: `frontend/src/pages/poster/PosterCleanarrPage.jsx` — Mode selector area (827-830) + clean body builder (638-650).

- [ ] **Step 1: Add checkbox state**

Near the `mode` state (line 399):

```javascript
    const [cleanBloat, setCleanBloat] = useState(true);
    const [cleanStale, setCleanStale] = useState(false);
    const [cleanOrphan, setCleanOrphan] = useState(false);
```

- [ ] **Step 2: Render the checkboxes next to the Mode selector**

After the Mode `<select>` block (line ~830), add (copy label/spacing classes from existing controls):

```javascript
                    <div className="flex items-center gap-3 ml-3 text-sm">
                        <label className="flex items-center gap-1 cursor-pointer">
                            <input type="checkbox" checked={cleanBloat}
                                onChange={e => setCleanBloat(e.target.checked)} />
                            Bloat
                        </label>
                        <label className="flex items-center gap-1 cursor-pointer">
                            <input type="checkbox" checked={cleanStale}
                                onChange={e => setCleanStale(e.target.checked)} />
                            Stale
                        </label>
                        <label className="flex items-center gap-1 cursor-pointer">
                            <input type="checkbox" checked={cleanOrphan}
                                onChange={e => setCleanOrphan(e.target.checked)} />
                            Orphan
                        </label>
                    </div>
```

- [ ] **Step 3: Feed selections into the cleanup body**

In the cleanup handler that builds `body` (around line 638-650), set the action-mode for each enabled cleaner. Bloat is governed by the existing top-level `mode`; stale/orphan get their own mode (reuse the same `mode` value so one selector drives all, which matches how the orphan inline pass mirrors Cleanarr's mode):

```javascript
            // Bloat: when unchecked, force the harmless "nothing" mode so the
            // job skips Plex-variant deletion but can still run stale/orphan.
            body.mode = cleanBloat ? mode : 'nothing';
            body.stale_duplicates_enabled = cleanStale;
            body.orphan_assets_enabled = cleanOrphan;
            if (cleanStale) body.stale_duplicates_mode = mode;
            if (cleanOrphan) body.orphan_assets_mode = mode;
```

NOTE: confirm the backend `run()` honors `mode == "nothing"` for the bloat branch (it does — line 152 only runs bloat for report/move/remove; `nothing` skips it) and that the orphan/stale blocks run independently of `mode` (they do — they gate on their own `*_enabled`). Verify `_build_cleanup_overrides` forwards `mode: "nothing"` — update its allowed set to include `"nothing"` if the checkbox path can send it:

In `_build_cleanup_overrides` (Task 9), change the mode validation to:
```python
    if mode not in ("report", "move", "remove", "nothing"):
        raise ValueError(f"Invalid mode '{mode}'")
```
and update Task 9's `test_cleanup_overrides_reject_bad_stale_mode` neighbours accordingly (the bloat `mode` now also accepts `nothing`).

- [ ] **Step 4: Browser check** — toggling Stale-only with mode=report enqueues a job; the job log shows the stale pass running and bloat skipped.

- [ ] **Step 5: Lint + commit**

```bash
npm --prefix frontend run lint && cd frontend && npx prettier --check src
git add frontend/src/pages/poster/PosterCleanarrPage.jsx
git commit -m "feat(frontend): clean-mode Bloat/Stale/Orphan checkboxes"
```

---

## Task 14: Detail-scope clarity label (the 28 vs 15 confusion)

**Files:**
- Modify: `frontend/src/pages/poster/PosterCleanarrPage.jsx` — detail header stats (~line 1039) and where `bloatInDetail` is shown.

- [ ] **Step 1: Label the detail bloat as the selected level**

Where the detail header renders the stats line (the one showing "N variants · X active · Y bloat · …", near line 1039 using `detail.variants.length`, `activeInDetail`, `bloatInDetail`), change the bloat span to clarify scope, e.g.:

```javascript
                                            <span className="text-error">
                                                {bloatInDetail} bloat here
                                            </span>
```

And add, when the selected node is a show with descendants, a muted subtree total. Compute it from the same tree the row uses (already available via `bundleTrees.get(bundle.rating_key)` — locate how the page accesses the tree for the selected bundle; it's the `tree` passed to `BundleTreeRow` and derived in the detail memo around line 550). Render:

```javascript
                                            {selected?.kind === 'show' && (
                                                <span className="text-tertiary">
                                                    · {subtreeBloat} in subtree
                                                </span>
                                            )}
```

where `subtreeBloat` is computed in the detail memo (mirror the `bloatCount` reducer from `BundleTreeRow` lines 1356-1362). If wiring the subtree total proves invasive, ship only the "bloat here" relabel — that alone resolves the confusion.

- [ ] **Step 2: Browser check** — selecting the show now reads "15 bloat here · 28 in subtree" (or just "15 bloat here").

- [ ] **Step 3: Lint + commit**

```bash
npm --prefix frontend run lint && cd frontend && npx prettier --check src
git add frontend/src/pages/poster/PosterCleanarrPage.jsx
git commit -m "fix(poster-cleanarr): clarify detail bloat is selected-level scope"
```

---

## Task 15: Scheduled-run coverage (all three cleaners, every mode)

A scheduled Poster Cleanarr run triggers `module_run` for `poster_cleanarr` using the SAVED config (not UI overrides). `run()` gates each cleaner on its own config flag/mode independently of the trigger, so a schedule with bloat `mode` + `orphan_assets_enabled`/`orphan_assets_mode` + `stale_duplicates_enabled`/`stale_duplicates_mode` runs all three in whatever modes are saved. This task locks that wiring with a test and confirms the schedule is configurable.

**Files:**
- Test: `tests/test_poster_cleanarr_duplicates.py`
- Verify: `backend/util/config.py`, `frontend/src/utils/constants/settings_schema.js`

- [ ] **Step 1: Confirm poster_cleanarr is schedulable**

Run: `cd /Users/dean/Code/GitHub/chub && grep -niE "schedule" backend/util/config.py | sed -n '1,40p'; grep -niE "schedule" frontend/src/utils/constants/settings_schema.js | head`
Expected: confirm a cron `schedule` mechanism applies to `poster_cleanarr` (shared scheduler or a per-module `schedule` field) and the settings UI exposes it. No code change if it already exists — this step only confirms a scheduled trigger path. If poster_cleanarr is NOT schedulable today, STOP and surface that to the requester before proceeding (it changes scope).

- [ ] **Step 2: Write the wiring test**

Append to `tests/test_poster_cleanarr_duplicates.py`:

```python
def test_run_invokes_orphan_and_stale_passes(monkeypatch, tmp_path):
    """run() with mode='nothing' (skips Plex/bloat) must still invoke BOTH the
    orphan and stale passes when their config flags are set — the path a
    SCHEDULED job takes, reading saved config. Proves all three cleaners are
    independently driven by config, so a schedule can run them in any mode."""
    import backend.modules.poster_cleanarr as mod

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod, "ChubDB", lambda *a, **k: _FakeDB())

    m = _make()
    m.mode = "nothing"
    m.plex_path = ""
    m.full_config = SimpleNamespace()
    m.config = SimpleNamespace(
        local_db=True,
        orphan_assets_enabled=True,
        orphan_assets_mode="report",
        stale_duplicates_enabled=True,
        stale_duplicates_mode="report",
        asset_dirs=[str(tmp_path)],
        instances=["sonarr"],
        orphan_instances=[],
        include_collections=True,
        orphan_ignore_titles=[],
    )
    calls = []
    monkeypatch.setattr(
        m, "_run_orphan_pass",
        lambda **k: calls.append("orphan") or {"count": 0, "total_size": 0},
    )
    monkeypatch.setattr(
        m, "_run_stale_pass",
        lambda **k: calls.append("stale") or {"count": 0, "total_size": 0},
    )
    m.run()
    assert "orphan" in calls
    assert "stale" in calls
```

NOTE: run() line 107 only validates plex_path for modes other than `"nothing"`, and line 138 sets `needs_plex=False` for `"nothing"`, so no Plex connection is attempted. If `run()` touches other `self.*` attrs before the cleaner blocks (e.g. `self.logger.log_outro()` in `finally` — provided by `_make`), add them to the fake until the test passes. Do NOT weaken the test to pass — fix the fake.

- [ ] **Step 3: Run the test**

Run: `python3 -m pytest tests/test_poster_cleanarr_duplicates.py::test_run_invokes_orphan_and_stale_passes -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_poster_cleanarr_duplicates.py
git commit -m "test(poster-cleanarr): scheduled run invokes orphan + stale passes"
```

---

## Task 16: Settings schema + full verification

**Files:**
- Modify: `frontend/src/utils/constants/settings_schema.js` (poster_cleanarr section, after the orphan fields ~line 1273)

- [ ] **Step 1: Add stale settings to the schema**

Mirror the orphan fields' shape (lines 1227-1273). Add:

```javascript
            {
                key: 'stale_duplicates_enabled',
                label: 'Enable Stale Duplicate Cleanup',
                type: 'boolean',
                section: 'Stale Duplicate Cleanup',
                help: 'Detects Kometa asset folders whose {tmdb-N}/{tvdb-N} id matches a live item but whose folder name no longer matches the media folder (e.g. after a Sonarr/Radarr folder rename). The canonical folder is always kept; a non-canonical duplicate is reported/moved/removed. Skipped if the canonical folder is not yet staged (never deletes the only copy).',
            },
            {
                key: 'stale_duplicates_mode',
                label: 'Stale Mode',
                type: 'select',
                options: ['report', 'move', 'remove'],
                section: 'Stale Duplicate Cleanup',
                help: 'report (log only) · move (to the restore dir, reversible) · remove (delete).',
            },
```

Match the exact object shape of the neighbouring orphan entries (copy their property names/keys verbatim — e.g. if they use `inputType` instead of `type`, or a `default` field, mirror that). Verify the field types are registered (the lint step runs `scripts/check-field-types.js`).

- [ ] **Step 2: Backend verification**

Run: `cd /Users/dean/Code/GitHub/chub && ruff check . && python3 -m pytest tests/test_poster_cleanarr.py tests/test_poster_cleanarr_orphans.py tests/test_poster_cleanarr_duplicates.py tests/test_posters_api_kometa_scan.py -q`
Expected: ruff clean; all tests pass.

- [ ] **Step 3: Frontend verification**

Run: `npm --prefix frontend run lint && cd frontend && npx prettier --check src`
Expected: lint passes (incl. "settings schema field types all registered"); prettier clean.

- [ ] **Step 4: Browser end-to-end (preview against live API)**

Per the project's verify workflow: start the dev server (temporarily point the Vite proxy at the live instance if needed — and REVERT it before committing), log in, open Poster Cleanarr, confirm:
- stale pills appear on the expected rows,
- the Orphaned-assets section renders (or is absent when empty),
- toggling Stale + Report mode + Run enqueues a job whose log shows the stale pass,
- bloat view + variant delete still work unchanged.
Capture a screenshot for the PR.

- [ ] **Step 5: Final commit**

```bash
git add frontend/src/utils/constants/settings_schema.js
git commit -m "feat(settings): add poster_cleanarr stale-duplicate settings"
```

---

## Self-Review Notes (for the implementer)

- **Naming consistency:** `_build_canonical_folder_map`, `_scan_stale_duplicates`, `_execute_stale_mode`, `_run_stale_pass`, `run_stale_duplicates_pass`, `_stale_rating_key_map`, `_build_cleanup_overrides`, `scanKometaAssets`, `stale_duplicates_enabled`/`stale_duplicates_mode`, `staleByRk`, `cleanBloat`/`cleanStale`/`cleanOrphan`, `stalePill`. Use these exact names everywhere.
- **Source-of-truth:** the endpoint (Task 8) and the job pass (Task 5) both call the same `_scan_stale_duplicates` + `_build_canonical_folder_map`. Never duplicate detection logic in the API layer.
- **Safety:** stale removal is gated on `canonical_present` (Task 4) so it can never delete the only staged copy. Detection is spare-only on the id (no live id → not flagged here).
- **Unverified-until-build:** (a) `tvdb_id_regex.search().group(1)` returns the integer string (Task 3 Step 4 verifies); (b) `db.media.execute_query(..., fetch=True)` row shape (Task 8 Step 3 NOTE); (c) the orphan settings object shape in settings_schema.js (Task 16 Step 1). Resolve each at its task before proceeding.
- **Scope guard:** all changes are on shared (main) files — no extension imports, no Dockerfile edits. After merging to develop, `git diff main develop` must remain added-files-only + the Dockerfile.
</content>
</invoke>

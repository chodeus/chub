# backend/extensions/__init__.py
"""Discovery point for self-registering backend extensions.

An extension is a subpackage of this package (``backend/extensions/<name>/``)
containing a ``manifest.py``. The manifest exposes zero or more hook
functions; each is optional and called at most once:

    routers()       -> list[fastapi.APIRouter]
        Routers to mount on the app (consumed by backend/api/main.py).
    modules()       -> dict[str, type]
        Module-name -> ChubModule subclass entries for the MODULES registry
        (consumed by backend/modules/__init__.py).
    config_fields() -> dict[str, tuple[type, Any]]
        Extra pydantic fields grafted onto ChubConfig via create_model —
        name -> (annotation, FieldInfo/default) as create_model expects
        (consumed by backend/util/config.py).
    tables()        -> list[TableDefinition]
        Extra database tables (consumed by SchemaManager.__init__).

Hook functions should import their payloads lazily (inside the function
body, not at manifest import time): manifests are imported while core
modules such as backend.util.config are still initialising, so a
module-level import of anything heavyweight risks a circular import.

On a branch with no extension subpackages (e.g. main) every aggregate
below returns empty, and the callers behave exactly as if this package
did not exist.
"""

import importlib
import pkgutil
from functools import lru_cache
from typing import Any, Dict, List, Tuple


@lru_cache(maxsize=1)
def _manifests() -> Tuple[Any, ...]:
    manifests = []
    for mod in pkgutil.iter_modules(__path__):
        if not mod.ispkg:
            continue
        manifests.append(importlib.import_module(f"{__name__}.{mod.name}.manifest"))
    return tuple(manifests)


def _collect(hook: str) -> List[Any]:
    results = []
    for manifest in _manifests():
        fn = getattr(manifest, hook, None)
        if callable(fn):
            results.append(fn())
    return results


def extension_routers() -> List[Any]:
    return [router for routers in _collect("routers") for router in routers]


def extension_modules() -> Dict[str, type]:
    merged: Dict[str, type] = {}
    for entry in _collect("modules"):
        merged.update(entry)
    return merged


def extension_config_fields() -> Dict[str, Tuple[type, Any]]:
    merged: Dict[str, Tuple[type, Any]] = {}
    for entry in _collect("config_fields"):
        merged.update(entry)
    return merged


def extension_tables() -> List[Any]:
    return [table for tables in _collect("tables") for table in tables]


def extension_notification_formatters() -> Dict[str, Any]:
    """Per-module Discord formatters contributed by extensions, keyed by module
    name. Each manifest's ``notification_formatters()`` returns
    ``{module_key: {"formatter": fn, "type": "embedded"|"flat"}}``. Merged into
    format_for_discord's registry so an extension module can format its own
    notification. Empty on main (no extensions)."""
    merged: Dict[str, Any] = {}
    for entry in _collect("notification_formatters"):
        merged.update(entry)
    return merged

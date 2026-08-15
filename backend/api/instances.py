"""
Service instance management API endpoints for CHUB.

Provides instance configuration, testing, and library
retrieval for Plex, Radarr, Sonarr, and Lidarr integrations.
"""

import os
import time
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.config import (
    REDACTED_PLACEHOLDER,
    ChubConfig,
    ConfigError,
    InstanceDetail,
    load_config,
    redact_secrets,
    save_config,
)
from backend.util import plex_library_cache
from backend.util.database import ChubDB

if os.environ.get("DOCKER_ENV"):
    LOG_BASE_DIR = "/config/logs"
else:
    LOG_BASE_DIR = str((Path(__file__).parents[2] / "logs").resolve())

router = APIRouter(
    prefix="/api",
    tags=["Service Instances"],
    responses={
        500: {"description": "Internal server error"},
        502: {"description": "External service connection failed"},
    },
)

_PLEX_CATALOG_TTL = 300.0

# Config fields that hold an instance-name reference, used to keep module
# cross-references (upgradinatorr/labelarr/nestarr/renameinatorr/… instance
# pointers) in sync when an instance is renamed.
_REF_STR_FIELDS = {"instance", "app_instance", "arr_instance"}
_REF_LIST_FIELDS = {"instances"}


def _rename_config_instance_refs(config: ChubConfig, old: str, new: str) -> int:
    """Recursively rewrite instance-name references across the config tree so a
    rename doesn't strand the modules that point at the instance by name.

    Walks pydantic models only; the ``instances`` Dict on InstancesConfig is a
    mapping (not a list of names) so it's skipped — the key rename is handled by
    the caller. Returns the number of references updated. The caller must ensure
    ``old`` is unambiguous (not also another service's instance) before calling,
    since matching is by exact name across every service's references.
    """

    def walk(node: Any) -> int:
        if not isinstance(node, BaseModel):
            return 0
        n = 0
        for fname in type(node).model_fields:
            val = getattr(node, fname, None)
            if fname in _REF_STR_FIELDS and isinstance(val, str):
                if val == old:
                    setattr(node, fname, new)
                    n += 1
            elif (
                fname in _REF_LIST_FIELDS
                and isinstance(val, list)
                and all(isinstance(x, str) for x in val)
            ):
                if old in val:
                    setattr(node, fname, [new if x == old else x for x in val])
                    n += val.count(old)
            elif isinstance(val, BaseModel):
                n += walk(val)
            elif isinstance(val, list):
                for item in val:
                    n += walk(item)
        return n

    return walk(config)


def _prune_module_library_refs(
    config: ChubConfig, instance_name: str, allowed: list
) -> int:
    """Drop per-module Plex library selections that reference a library the
    instance is no longer opted into.

    Walks the config tree for any model carrying BOTH an ``instance`` name and a
    ``library_names`` list (PlexScope / LabelarrPlexInstance / NestarrPlexInstance,
    incl. nestarr's nested library_mappings) and, where ``instance`` matches,
    filters ``library_names`` to the allow-list. Keeps the global opt-in the single
    source of truth so no read/apply path can target a de-selected library.
    Returns the number of library references removed.
    """
    allowed_norm = {
        name.strip().lower() for name in (allowed or []) if isinstance(name, str)
    }

    def walk(node: Any) -> int:
        if not isinstance(node, BaseModel):
            return 0
        n = 0
        fields = type(node).model_fields
        if "instance" in fields and "library_names" in fields:
            if getattr(node, "instance", None) == instance_name:
                libs = getattr(node, "library_names", None)
                if isinstance(libs, list) and libs:
                    kept = [
                        lib
                        for lib in libs
                        if isinstance(lib, str) and lib.strip().lower() in allowed_norm
                    ]
                    if len(kept) != len(libs):
                        setattr(node, "library_names", kept)
                        n += len(libs) - len(kept)
        for fname in fields:
            val = getattr(node, fname, None)
            if isinstance(val, BaseModel):
                n += walk(val)
            elif isinstance(val, list):
                for item in val:
                    n += walk(item)
        return n

    return walk(config)


class TestInstanceRequest(BaseModel):
    """Request schema for testing a service instance."""

    service: Optional[str] = None
    name: str
    url: str
    api: Optional[str] = None
    type: Optional[str] = None
    apiKey: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, values):
        """Accept frontend field names (type, apiKey) alongside backend names."""
        if isinstance(values, dict):
            if values.get("type") and not values.get("service"):
                values["service"] = values["type"]
            if values.get("apiKey") and not values.get("api"):
                values["api"] = values["apiKey"]
        return values


class CreateInstanceRequest(BaseModel):
    """Request schema for creating a service instance."""

    service: Optional[str] = None
    name: str
    url: str
    api: Optional[str] = None
    type: Optional[str] = None
    apiKey: Optional[str] = None
    webhook_force_reupload: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, values):
        """Accept frontend field names (type, apiKey) alongside backend names."""
        if isinstance(values, dict):
            if values.get("type") and not values.get("service"):
                values["service"] = values["type"]
            if values.get("apiKey") and not values.get("api"):
                values["api"] = values["apiKey"]
        return values


class UpdateInstanceRequest(BaseModel):
    """Request schema for updating a service instance."""

    service: Optional[str] = None
    name: str
    url: str
    api: Optional[str] = None
    type: Optional[str] = None
    apiKey: Optional[str] = None
    webhook_force_reupload: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, values):
        """Accept frontend field names (type, apiKey) alongside backend names."""
        if isinstance(values, dict):
            if values.get("type") and not values.get("service"):
                values["service"] = values["type"]
            if values.get("apiKey") and not values.get("api"):
                values["api"] = values["apiKey"]
        return values


def get_config() -> ChubConfig:
    """Load and return the current configuration."""
    return load_config()


# --- New endpoints: types, health (must be before /{id}) ---


@router.get(
    "/instances/types",
    summary="Get supported instance types",
    description="Retrieve the list of supported service instance types.",
    responses={
        200: {
            "description": "Supported instance types retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Supported instance types",
                        "data": {
                            "types": [
                                {
                                    "name": "plex",
                                    "label": "Plex",
                                    "description": "Plex Media Server",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
async def get_instance_types(
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve the list of supported service instance types.

    Returns all service types that can be configured as instances,
    including display labels and descriptions for each type.

    Returns:
        List of supported instance types with metadata
    """
    try:
        logger.debug("Serving GET /api/instances/types")
        types = [
            {"name": "plex", "label": "Plex", "description": "Plex Media Server"},
            {"name": "radarr", "label": "Radarr", "description": "Movie management"},
            {
                "name": "sonarr",
                "label": "Sonarr",
                "description": "TV series management",
            },
            {
                "name": "lidarr",
                "label": "Lidarr",
                "description": "Music management",
            },
        ]
        return ok("Supported instance types", {"types": types})
    except Exception as e:
        logger.error(f"Error retrieving instance types: {e}")
        return error(
            "Failed to retrieve instance types", code="TYPES_ERROR", status_code=500
        )


@router.get(
    "/instances/types/{instance_type}/schema",
    summary="Get instance type schema",
    description="Retrieve the configuration schema for a specific instance type.",
    responses={
        200: {
            "description": "Instance type schema retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Schema for radarr",
                        "data": {
                            "schema": [
                                {
                                    "name": "url",
                                    "type": "string",
                                    "required": True,
                                    "label": "Server URL",
                                    "placeholder": "http://localhost:7878",
                                }
                            ]
                        },
                    }
                }
            },
        },
        404: {"description": "Unknown instance type"},
    },
)
async def get_instance_type_schema(
    instance_type: str,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve the configuration schema for a specific instance type.

    Returns the field definitions needed to configure an instance of
    the given type, including required fields, labels, and placeholders.

    Args:
        instance_type: Service type to get the schema for (plex, radarr, sonarr, lidarr)

    Returns:
        Configuration schema fields for the requested type
    """
    try:
        logger.debug(f"Serving GET /api/instances/types/{instance_type}/schema")
        schemas = {
            "plex": [
                {
                    "name": "url",
                    "type": "string",
                    "required": True,
                    "label": "Server URL",
                    "placeholder": "http://localhost:32400",
                },
                {
                    "name": "api",
                    "type": "string",
                    "required": True,
                    "label": "API Token",
                    "placeholder": "Plex token",
                },
            ],
            "radarr": [
                {
                    "name": "url",
                    "type": "string",
                    "required": True,
                    "label": "Server URL",
                    "placeholder": "http://localhost:7878",
                },
                {
                    "name": "api",
                    "type": "string",
                    "required": True,
                    "label": "API Key",
                    "placeholder": "Radarr API key",
                },
            ],
            "sonarr": [
                {
                    "name": "url",
                    "type": "string",
                    "required": True,
                    "label": "Server URL",
                    "placeholder": "http://localhost:8989",
                },
                {
                    "name": "api",
                    "type": "string",
                    "required": True,
                    "label": "API Key",
                    "placeholder": "Sonarr API key",
                },
            ],
            "lidarr": [
                {
                    "name": "url",
                    "type": "string",
                    "required": True,
                    "label": "Server URL",
                    "placeholder": "http://localhost:8686",
                },
                {
                    "name": "api",
                    "type": "string",
                    "required": True,
                    "label": "API Key",
                    "placeholder": "Lidarr API key",
                },
            ],
        }
        if instance_type not in schemas:
            return error(
                f"Unknown instance type: {instance_type}",
                code="UNKNOWN_TYPE",
                status_code=404,
            )
        return ok(f"Schema for {instance_type}", {"schema": schemas[instance_type]})
    except Exception as e:
        logger.error(f"Error retrieving schema: {e}")
        return error(
            "Failed to retrieve instance schema", code="SCHEMA_ERROR", status_code=500
        )


@router.get(
    "/instances/health",
    summary="Check all instance health",
    description="Check connectivity health of all configured service instances.",
    responses={
        200: {
            "description": "Health check results for all instances",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Health checked for 3 instances",
                        "data": {
                            "health": {
                                "main": {
                                    "service": "plex",
                                    "status": "healthy",
                                    "status_code": 200,
                                    "response_time_ms": 45,
                                }
                            }
                        },
                    }
                }
            },
        }
    },
)
def check_all_health(
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Check connectivity health of all configured instances.

    Iterates through every configured Plex, Radarr, Sonarr, and Lidarr instance,
    tests connectivity, and returns the health status with response times.

    Returns:
        Health status for each configured instance
    """
    try:
        logger.debug("Serving GET /api/instances/health")
        from concurrent.futures import ThreadPoolExecutor

        from backend.util.ssrf_guard import is_safe_url

        results = {}
        probes = []  # (service, name, test_url, headers) for reachable targets

        for service in ["plex", "radarr", "sonarr", "lidarr"]:
            instances = getattr(config.instances, service, {})
            for name, details in instances.items():
                url = details.url.rstrip("/") if details.url else ""
                api = details.api or ""

                if service == "plex":
                    headers = {"X-Plex-Token": api} if api else {}
                    test_url = f"{url}/library/sections"
                else:
                    headers = {"X-Api-Key": api} if api else {}
                    api_ver = "v1" if service == "lidarr" else "v3"
                    test_url = f"{url}/api/{api_ver}/system/status"

                safe, reason = is_safe_url(test_url)
                if not safe:
                    results[name] = {
                        "service": service,
                        "status": "blocked",
                        "error": f"URL refused: {reason}",
                    }
                    continue

                probes.append((service, name, test_url, headers))

        # Probe instances concurrently — each requests.get opens its own
        # connection (thread-safe), so a multi-instance setup no longer waits
        # serially (was up to ~2s per instance back-to-back).
        def _probe(probe):
            service, name, test_url, headers = probe
            start = time.time()
            try:
                resp = requests.get(
                    test_url, headers=headers, timeout=2, allow_redirects=False
                )
                elapsed = round((time.time() - start) * 1000)
                return name, {
                    "service": service,
                    "status": "healthy" if resp.ok else "unhealthy",
                    "status_code": resp.status_code,
                    "response_time_ms": elapsed,
                }
            except requests.exceptions.Timeout:
                return name, {
                    "service": service,
                    "status": "timeout",
                    "response_time_ms": 2000,
                }
            except requests.exceptions.ConnectionError:
                return name, {
                    "service": service,
                    "status": "unreachable",
                    "response_time_ms": 0,
                }
            except Exception as exc:
                logger.error(f"Health probe failed for '{name}': {exc}")
                return name, {
                    "service": service,
                    "status": "error",
                }

        if probes:
            with ThreadPoolExecutor(max_workers=min(10, len(probes))) as pool:
                for name, result in pool.map(_probe, probes):
                    results[name] = result

        return ok(f"Health checked for {len(results)} instances", {"health": results})
    except Exception as e:
        logger.error(f"Error checking instance health: {e}")
        return error("Health check failed", code="HEALTH_CHECK_ERROR", status_code=500)


# --- Existing endpoints below ---


@router.get(
    "/instances",
    summary="Get service instances",
    description="Retrieve all configured Plex, Radarr, Sonarr, and Lidarr service instances.",
    responses={
        200: {
            "description": "Service instances retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instances retrieved successfully",
                        "data": {
                            "plex": {
                                "main": {
                                    "url": "http://localhost:32400",
                                    "api": "abc123",
                                }
                            },
                            "radarr": {},
                            "sonarr": {},
                        },
                    }
                }
            },
        }
    },
)
async def get_instances(
    type: Optional[str] = None,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve all configured service instances.

    Returns the complete configuration for all Plex, Radarr,
    Sonarr, and Lidarr instances including URLs and API credentials
    (masked for security). Used by the UI for instance selection.

    Optionally filter by service type using the ``type`` query parameter.

    Args:
        type: Optional service type filter (plex, radarr, sonarr, or lidarr)

    Returns:
        Complete service instance configuration
    """
    try:
        logger.debug("Serving GET /api/instances")
        instances_data = redact_secrets(config.instances.model_dump(mode="python"))

        if type:
            filter_type = type.lower()
            instances_data = {
                k: v for k, v in instances_data.items() if k == filter_type
            }

        return ok(
            "Instances retrieved successfully",
            instances_data,
        )

    except Exception as e:
        logger.error(f"Error retrieving instances: {e}")
        return error(
            "Error retrieving instances",
            code="INSTANCES_RETRIEVAL_ERROR",
            status_code=500,
        )


class _PlexFetchError(Exception):
    """Carries the API error code/status the libraries endpoints surface."""

    def __init__(
        self, message: str, code: str, status_code: int, detail: str = ""
    ) -> None:
        """Split the public message from the server-only `detail`."""
        super().__init__(message)
        self.message = message  # public: returned to the client
        self.detail = detail  # server-only: never put in a response
        self.code = code
        self.status_code = status_code


def _fetch_plex_libraries(plex_data: Any) -> list:
    """Fetch library sections ``[{title, type}]`` from one Plex instance.

    Raises ``_PlexFetchError`` (with the same code/status the single-instance
    endpoint reports) on missing credentials, connection failure, a non-OK Plex
    response, or unparseable XML. Shared by the single-instance endpoint and the
    cached catalog endpoint so the fetch/parse logic lives in one place.
    """
    base_url = getattr(plex_data, "url", None)
    token = getattr(plex_data, "api", None)
    if not base_url or not token:
        raise _PlexFetchError(
            "Missing Plex API credentials for instance",
            "PLEX_CREDENTIALS_MISSING",
            400,
        )
    headers = {"X-Plex-Token": token}
    url = f"{base_url}/library/sections"

    from backend.util.ssrf_guard import is_safe_url

    safe, reason = is_safe_url(url)
    if not safe:
        raise _PlexFetchError(f"URL refused: {reason}", "URL_BLOCKED", 400)
    try:
        res = requests.get(url, headers=headers, timeout=5, allow_redirects=False)
    except requests.exceptions.RequestException as req_exc:
        raise _PlexFetchError(
            "Failed to connect to Plex server",
            "PLEX_CONNECTION_FAILED",
            502,
        ) from req_exc
    if not res.ok:
        raise _PlexFetchError(
            "Plex server error",
            "PLEX_SERVER_ERROR",
            res.status_code,
            detail=res.text[:500],
        )

    import defusedxml.ElementTree as ET

    # Plex returns each library section as a <Directory> carrying both a
    # human-readable `title` and an authoritative `type` (movie/show/artist/
    # photo) — surfacing `type` lets the UI categorize without title matching.
    root = ET.fromstring(res.text)
    return [
        {"title": el.attrib["title"], "type": el.attrib.get("type", "")}
        for el in root.findall(".//Directory")
        if "title" in el.attrib
    ]


def _annotate_enabled(libraries: list, enabled_libraries: Optional[list]) -> list:
    """Tag each ``{title, type}`` with ``enabled`` from the instance opt-in list.

    Annotates AFTER the TTL cache (never inside the fetch), so the cache holds the
    full library set and the opt-in UI can still show un-opted libraries. Mirrors
    the connector's tri-state: ``None`` (legacy/unset) == all enabled; ``[]`` == all
    disabled; a list enables exactly its (case-insensitive) members.
    """
    if enabled_libraries is None:
        allowed_norm = None
    else:
        allowed_norm = {
            name.strip().lower() for name in enabled_libraries if isinstance(name, str)
        }
    out = []
    for lib in libraries or []:
        title = lib.get("title") if isinstance(lib, dict) else str(lib)
        enabled = (
            True
            if allowed_norm is None
            else (title or "").strip().lower() in allowed_norm
        )
        out.append(
            {**(lib if isinstance(lib, dict) else {"title": title}), "enabled": enabled}
        )
    return out


@router.get(
    "/plex/libraries",
    summary="Get all Plex libraries (catalog)",
    description=(
        "Cached map of every configured Plex instance to its libraries. Backs "
        "the Settings→Instances catalog and the module library pickers."
    ),
)
def get_plex_libraries_catalog(
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Return ``{instance_name: [{title, type}, ...]}`` for all Plex instances.

    Each instance is served through a short TTL cache so the page/pickers don't
    re-hit Plex on every render. A per-instance fetch failure yields ``[]`` for
    that instance and a warning rather than failing the whole response."""
    catalog: dict = {}
    for name in config.instances.plex or {}:
        try:
            libs = plex_library_cache.get_cached_libraries(
                name,
                fetch=lambda n: _fetch_plex_libraries(config.instances.plex[n]),
                ttl_seconds=_PLEX_CATALOG_TTL,
                now=time.monotonic(),
            )
            catalog[name] = _annotate_enabled(
                libs, config.instances.plex[name].enabled_libraries
            )
        except Exception as exc:
            logger.warning(
                "Catalog: failed to fetch libraries for Plex '%s': %s", name, exc
            )
            catalog[name] = []
    return ok(
        f"Retrieved libraries for {len(catalog)} Plex instance(s)",
        {"libraries": catalog},
    )


@router.get(
    "/plex/{instance}/libraries",
    summary="Get Plex libraries",
    description="Retrieve available library sections from a specific Plex instance.",
    responses={
        200: {
            "description": "Plex libraries retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 2 libraries for Plex instance 'main'",
                        "data": {
                            "libraries": [
                                {"title": "Movies", "type": "movie"},
                                {"title": "TV Shows", "type": "show"},
                            ]
                        },
                    }
                }
            },
        },
        404: {"description": "Plex instance not found in configuration"},
        502: {"description": "Failed to connect to Plex server"},
    },
)
def get_plex_libraries(
    instance: str,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve library sections from a Plex instance.

    Connects to the specified Plex instance using configured
    credentials and returns available library sections for
    configuration and filtering purposes.

    Args:
        instance: Name of the Plex instance from configuration

    Returns:
        List of available Plex libraries with their type
        (e.g. ``{"title": "Movies", "type": "movie"}``).
    """
    try:
        logger.debug("Serving GET /api/plex/libraries for instance: %s", instance)

        plex_data = config.instances.plex.get(instance)
        if not plex_data:
            return error(
                f"Plex instance '{instance}' not found",
                code="PLEX_INSTANCE_NOT_FOUND",
                status_code=404,
            )

        try:
            libraries = _fetch_plex_libraries(plex_data)
        except _PlexFetchError as fe:
            # exc_info carries the __cause__ the public message no longer does
            logger.error(
                "Plex libraries fetch failed: %s %s",
                fe.message,
                fe.detail,
                exc_info=True,
            )
            return error(fe.message, code=fe.code, status_code=fe.status_code)

        libraries = _annotate_enabled(libraries, plex_data.enabled_libraries)
        return ok(
            f"Retrieved {len(libraries)} libraries for Plex instance '{instance}'",
            {"libraries": libraries},
        )

    except Exception as e:
        logger.error(f"Unexpected error retrieving Plex libraries: {e}")
        return error(
            "Error retrieving Plex libraries",
            code="PLEX_LIBRARIES_ERROR",
            status_code=500,
        )


class UpdateLibrariesRequest(BaseModel):
    """Request schema for setting a Plex instance's opted-in libraries."""

    enabled_libraries: list = []


@router.patch(
    "/plex/{instance}/libraries",
    summary="Set opted-in Plex libraries",
    description=(
        "Replace a Plex instance's library opt-in allow-list. Libraries not in the "
        "list are hidden everywhere CHUB manages content, their cached rows are "
        "purged, and any per-module selection referencing them is pruned. This is "
        "the sole writer of enabled_libraries (the Add/Edit form never touches it)."
    ),
    responses={
        200: {"description": "Opt-in updated"},
        404: {"description": "Plex instance not found in configuration"},
    },
)
async def update_instance_libraries(
    instance: str,
    data: UpdateLibrariesRequest,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Set the opt-in allow-list for a Plex instance.

    Persists ``enabled_libraries`` (de-duped, order preserved), prunes stale
    per-module selections, invalidates the library catalog cache, and purges
    plex_media_cache / collections_cache rows for de-selected libraries so they
    stop surfacing in stats/search/matching.
    """
    plex_instances = config.instances.plex
    detail = plex_instances.get(instance)
    if not detail:
        return error(
            f"Plex instance '{instance}' not found",
            code="PLEX_INSTANCE_NOT_FOUND",
            status_code=404,
        )

    new_enabled = [
        lib
        for lib in dict.fromkeys(data.enabled_libraries or [])
        if isinstance(lib, str)
    ]
    detail.enabled_libraries = new_enabled
    allowed_norm = {lib.strip().lower() for lib in new_enabled}

    pruned_refs = _prune_module_library_refs(config, instance, new_enabled)

    save_config(config)
    plex_library_cache.invalidate(instance)

    purged_rows = 0
    try:
        with ChubDB(logger=logger) as db:
            for lib in db.plex.get_library_names_for_instance(instance):
                if lib.strip().lower() not in allowed_norm:
                    purged_rows += db.plex.clear_library(instance, lib) or 0
            for lib in db.collection.get_library_names_for_instance(instance):
                if lib.strip().lower() not in allowed_norm:
                    db.collection.clear_library(instance, lib)
    except Exception as exc:
        logger.warning(
            "Library opt-in for '%s' saved, but cache purge failed: %s", instance, exc
        )

    logger.info(
        "Plex '%s' opt-in set to %d librar%s (pruned %d module ref(s), purged %d "
        "cached row(s))",
        instance,
        len(new_enabled),
        "y" if len(new_enabled) == 1 else "ies",
        pruned_refs,
        purged_rows,
    )
    return ok(
        f"Updated library opt-in for '{instance}' ({len(new_enabled)} enabled)",
        {
            "instance": instance,
            "enabled_libraries": new_enabled,
            "pruned_module_refs": pruned_refs,
            "purged_rows": purged_rows,
        },
    )


@router.post(
    "/instances/test",
    summary="Test service instance",
    description="Test connectivity and authentication for a service instance.",
    responses={
        200: {
            "description": "Connection test successful",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Connection to Plex Main successful",
                        "data": {"status_code": 200},
                    }
                }
            },
        },
        401: {"description": "Authentication failed - invalid credentials"},
        404: {"description": "Service not found - invalid URL"},
        408: {"description": "Connection timeout"},
        502: {"description": "Connection failed - unable to reach server"},
    },
)
def test_instance(
    data: TestInstanceRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Test connectivity and authentication for a service instance.

    Validates that the provided URL and API credentials can successfully
    connect to the specified service. Used during configuration to verify
    instance settings before saving.

    Args:
        data: Service instance details to test (service type, name, URL, API key)

    Returns:
        Connection test results with status and error details
    """
    try:
        service = data.service
        name = data.name
        url = data.url
        api = data.api

        # Resolve the redacted placeholder to the stored key ONLY for the instance
        # whose stored URL matches the target — never send a stored key to an
        # arbitrary URL, which would exfiltrate it to an attacker-controlled host.
        if api == REDACTED_PLACEHOLDER:
            config = load_config()
            service_instances = getattr(config.instances, service, {})
            target = (url or "").rstrip("/")
            stored = service_instances.get(name)
            stored_url = ""
            if stored is not None:
                stored_url = (
                    stored.url if hasattr(stored, "url") else stored.get("url")
                ) or ""
            # Not under this name (e.g. a rename): match on the stable URL identity.
            if stored is None or stored_url.rstrip("/") != target:
                stored = None
                for inst_cfg in service_instances.values():
                    inst_url = (
                        inst_cfg.url
                        if hasattr(inst_cfg, "url")
                        else inst_cfg.get("url")
                    ) or ""
                    if inst_url.rstrip("/") == target:
                        stored = inst_cfg
                        break
            if stored is not None:
                api = stored.api if hasattr(stored, "api") else stored.get("api")

        logger.info(f"Testing connection to {name.upper()} - URL: {url}")

        if not url:
            return error(
                "URL is required for instance testing",
                code="URL_MISSING",
                status_code=400,
            )

        url = url.rstrip("/")

        if service == "plex":
            headers = {"X-Plex-Token": api} if api else {}
            test_url = f"{url}/library/sections"
        else:
            headers = {"X-Api-Key": api} if api else {}
            api_ver = "v1" if service == "lidarr" else "v3"
            test_url = f"{url}/api/{api_ver}/system/status"

        logger.debug(f"Testing connection to: {test_url}")

        from backend.util.ssrf_guard import is_safe_url

        safe, reason = is_safe_url(test_url)
        if not safe:
            return error(
                f"URL refused: {reason}",
                code="URL_BLOCKED",
                status_code=400,
            )

        # No redirects: is_safe_url validated this exact host, but a public URL
        # could 302 onto an internal address (SSRF) if we followed them.
        resp = requests.get(test_url, headers=headers, timeout=5, allow_redirects=False)

        if resp.ok:
            logger.info(f"Connection test successful for {name}")
            return ok(
                f"Connection to {name} successful",
                {"status_code": resp.status_code},
            )

        error_messages = {
            401: "Unauthorized - Invalid credentials",
            404: "Not Found - Invalid URL or endpoint",
            403: "Forbidden - Access denied",
        }

        error_message = error_messages.get(
            resp.status_code, f"Server error: {resp.text}"
        )
        logger.error(
            f"Connection test failed with status {resp.status_code}: {error_message}"
        )

        return error(
            error_message,
            code=f"HTTP_{resp.status_code}",
            status_code=resp.status_code,
        )

    except requests.exceptions.Timeout:
        logger.error(f"Connection test timeout for {data.name} ({data.url})")
        return error(
            "Connection timeout - server did not respond",
            code="CONNECTION_TIMEOUT",
            status_code=408,
        )
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error for {data.name} ({data.url})")
        return error(
            "Connection failed - unable to reach server",
            code="CONNECTION_FAILED",
            status_code=502,
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Connection test failed for {data.name} ({data.url}): {e}")
        return error(
            "Connection test error",
            code="CONNECTION_TEST_ERROR",
            status_code=500,
        )


@router.post(
    "/instances",
    summary="Create service instance",
    description="Create a new Plex, Radarr, Sonarr, or Lidarr service instance in configuration.",
    responses={
        200: {
            "description": "Instance created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instance 'radarr_hd' created successfully",
                        "data": {"service": "radarr", "name": "radarr_hd"},
                    }
                }
            },
        },
        400: {"description": "Invalid service type or instance already exists"},
        500: {"description": "Configuration save failed"},
    },
)
async def create_instance(
    data: CreateInstanceRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Create a new service instance in configuration.

    Validates the service type, ensures the instance name doesn't already exist,
    and persists the new instance to config.yml.

    Args:
        data: Instance details (service type, name, URL, API key)

    Returns:
        Success confirmation with created instance details
    """
    try:
        service = data.service.lower()
        name = data.name
        url = data.url.rstrip("/")
        api_key = data.api

        logger.info(f"Creating new {service} instance: {name}")

        # Validate service type
        if service not in ["plex", "radarr", "sonarr", "lidarr"]:
            return error(
                f"Invalid service type: {service}. Must be plex, radarr, sonarr, or lidarr",
                code="INVALID_SERVICE_TYPE",
                status_code=400,
            )

        # A new instance has no stored key to fall back on — the redacted
        # placeholder is never a valid API key here.
        if api_key == REDACTED_PLACEHOLDER:
            return error(
                "A real API key is required for a new instance (received the "
                "redacted placeholder).",
                code="INVALID_API_KEY",
                status_code=400,
            )

        # Load current config
        config = load_config()

        # Check if instance already exists
        service_instances = getattr(config.instances, service)
        if name in service_instances:
            return error(
                f"Instance '{name}' already exists for service '{service}'",
                code="INSTANCE_ALREADY_EXISTS",
                status_code=400,
            )

        # Create new instance detail. A brand-new Plex server starts OPTED OUT
        # (enabled_libraries=[]) so nothing surfaces in CHUB until the user opts
        # each library in on the Instances page. Non-Plex services leave the field
        # unset (None) — it's meaningless for them.
        new_instance = InstanceDetail(
            url=url,
            api=api_key,
            webhook_force_reupload=data.webhook_force_reupload,
            enabled_libraries=[] if service == "plex" else None,
        )

        # Add to appropriate service section
        service_instances[name] = new_instance

        # Save updated configuration
        save_config(config)
        plex_library_cache.invalidate()

        logger.info(f"Successfully created {service} instance: {name}")
        return ok(
            f"Instance '{name}' created successfully",
            {"service": service, "name": name},
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to create instance {data.name}: {e}")
        return error(
            "Failed to create instance",
            code="INSTANCE_CREATE_ERROR",
            status_code=500,
        )


@router.put(
    "/instances/{instance_id}",
    summary="Update service instance",
    description="Update an existing Plex, Radarr, Sonarr, or Lidarr service instance configuration.",
    responses={
        200: {
            "description": "Instance updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instance 'radarr_hd' updated successfully",
                        "data": {"service": "radarr", "name": "radarr_hd"},
                    }
                }
            },
        },
        404: {"description": "Instance not found"},
        400: {"description": "Invalid service type"},
        500: {"description": "Configuration save failed"},
    },
)
async def update_instance(
    instance_id: str,
    data: UpdateInstanceRequest,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Update an existing service instance configuration.

    Validates the service type, ensures the instance exists, and updates
    the URL and API key in config.yml. Supports renaming instances.

    Args:
        instance_id: Current instance name (from URL path)
        data: Updated instance details (service type, name, URL, API key)

    Returns:
        Success confirmation with updated instance details
    """
    try:
        service = data.service.lower()
        new_name = data.name
        url = data.url.rstrip("/")
        api_key = data.api

        logger.info(f"Updating {service} instance: {instance_id}")

        # Validate service type
        if service not in ["plex", "radarr", "sonarr", "lidarr"]:
            return error(
                f"Invalid service type: {service}. Must be plex, radarr, sonarr, or lidarr",
                code="INVALID_SERVICE_TYPE",
                status_code=400,
            )

        # Load current config
        config = load_config()

        # Get service instances
        service_instances = getattr(config.instances, service)

        # Check if instance exists
        if instance_id not in service_instances:
            return error(
                f"Instance '{instance_id}' not found for service '{service}'",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )

        # Snapshot the existing instance BEFORE any rename `del` so fields the
        # edit form doesn't carry (enabled toggle, Plex library opt-in) survive
        # the rebuild below instead of silently resetting to their defaults.
        existing_instance = service_instances.get(instance_id)

        # Preserve the stored API key when the frontend sent the redacted
        # placeholder (an edit that didn't retype the key) — otherwise we'd
        # clobber the real key with "********" and break the connection.
        if api_key == REDACTED_PLACEHOLDER:
            stored = service_instances.get(instance_id)
            if stored:
                api_key = stored.api if hasattr(stored, "api") else stored.get("api")

        # Handle renaming: if new name differs from instance_id
        renaming = new_name != instance_id
        if renaming:
            # Check if new name already exists
            if new_name in service_instances:
                return error(
                    f"Instance '{new_name}' already exists for service '{service}'",
                    code="INSTANCE_NAME_CONFLICT",
                    status_code=400,
                )

            # Remove old instance
            del service_instances[instance_id]
            logger.info(f"Renaming instance from '{instance_id}' to '{new_name}'")

            # Rewrite module cross-references (upgradinatorr/labelarr/nestarr/…
            # instance pointers) — but only when the old name is unambiguous, so
            # a same-named instance of another service isn't caught by the
            # exact-name rewrite.
            others = [t for t in ("plex", "radarr", "sonarr", "lidarr") if t != service]
            if any(instance_id in getattr(config.instances, t) for t in others):
                logger.warning(
                    f"'{instance_id}' is also another service's instance name; "
                    f"skipping config cross-reference rewrite to avoid touching it"
                )
            else:
                refs = _rename_config_instance_refs(config, instance_id, new_name)
                if refs:
                    logger.info(
                        f"Updated {refs} config reference(s) from '{instance_id}' "
                        f"to '{new_name}'"
                    )

        # Create/update instance with new values. Carry forward the fields the
        # edit form doesn't send — the enabled toggle (owned by toggle_instance)
        # and the Plex library opt-in (owned by update_instance_libraries) — so
        # an edit to URL/key/webhook doesn't wipe them.
        updated_instance = InstanceDetail(
            url=url,
            api=api_key,
            webhook_force_reupload=data.webhook_force_reupload,
            enabled=getattr(existing_instance, "enabled", True),
            enabled_libraries=getattr(existing_instance, "enabled_libraries", None),
        )
        service_instances[new_name] = updated_instance

        # Save updated configuration
        save_config(config)
        plex_library_cache.invalidate()

        # Migrate cached DB rows (stats/freshness/progress) to the new name so
        # the rename is seamless. Config is the source of truth and already
        # saved, so a migration hiccup is logged but doesn't fail the request
        # (a re-sync would repopulate under the new name).
        if renaming:
            try:
                migrated = db.rename_instance(instance_id, new_name, service)
                logger.info(
                    f"Migrated {migrated} cached row(s) from '{instance_id}' to "
                    f"'{new_name}'"
                )
            except Exception as e:
                logger.error(f"Cache migration after rename failed: {e}")

        logger.info(f"Successfully updated {service} instance: {new_name}")
        return ok(
            f"Instance '{new_name}' updated successfully",
            {"service": service, "name": new_name},
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to update instance {instance_id}: {e}")
        return error(
            "Failed to update instance",
            code="INSTANCE_UPDATE_ERROR",
            status_code=500,
        )


@router.delete(
    "/instances/{instance_id}",
    summary="Delete service instance",
    description="Remove a Plex, Radarr, Sonarr, or Lidarr service instance from configuration.",
    responses={
        200: {
            "description": "Instance deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instance 'radarr_hd' deleted successfully",
                        "data": {"name": "radarr_hd"},
                    }
                }
            },
        },
        404: {"description": "Instance not found"},
        400: {"description": "Service type required in query parameter"},
        500: {"description": "Configuration save failed"},
    },
)
async def delete_instance(
    instance_id: str, service: str, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Delete a service instance from configuration.

    Removes the specified instance from the appropriate service section
    in config.yml. This operation is permanent.

    Args:
        instance_id: Instance name to delete
        service: Service type (plex, radarr, sonarr, or lidarr) as query parameter

    Returns:
        Success confirmation with deleted instance name
    """
    try:
        service = service.lower()

        logger.info(f"Deleting {service} instance: {instance_id}")

        # Validate service type
        if service not in ["plex", "radarr", "sonarr", "lidarr"]:
            return error(
                f"Invalid service type: {service}. Must be plex, radarr, sonarr, or lidarr",
                code="INVALID_SERVICE_TYPE",
                status_code=400,
            )

        # Load current config
        config = load_config()

        # Get service instances
        service_instances = getattr(config.instances, service)

        # Check if instance exists
        if instance_id not in service_instances:
            return error(
                f"Instance '{instance_id}' not found for service '{service}'",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )

        # Delete the instance
        del service_instances[instance_id]

        # Save updated configuration
        save_config(config)
        plex_library_cache.invalidate()

        logger.info(f"Successfully deleted {service} instance: {instance_id}")
        return ok(
            f"Instance '{instance_id}' deleted successfully",
            {"name": instance_id},
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete instance {instance_id}: {e}")
        return error(
            "Failed to delete instance",
            code="INSTANCE_DELETE_ERROR",
            status_code=500,
        )


# --- Additional instance endpoints ---


def _find_instance(config: ChubConfig, instance_id: str):
    """Look up an instance across all service types."""
    for service in ["plex", "radarr", "sonarr", "lidarr"]:
        instances = getattr(config.instances, service, {})
        if instance_id in instances:
            return service, instances[instance_id]
    return None, None


@router.get(
    "/instances/{instance_id}",
    summary="Get single instance",
    description="Retrieve details for a specific service instance by name.",
    responses={
        200: {
            "description": "Instance details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instance 'main' retrieved",
                        "data": {
                            "url": "http://localhost:32400",
                            "api": "abc123",
                            "name": "main",
                            "service": "plex",
                        },
                    }
                }
            },
        },
        404: {"description": "Instance not found"},
    },
)
async def get_single_instance(
    instance_id: str,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve details for a specific service instance by name.

    Searches across all service types (Plex, Radarr, Sonarr, Lidarr) to find
    the instance matching the given ID.

    Args:
        instance_id: Name of the instance to retrieve

    Returns:
        Instance configuration including URL, API key, name, and service type
    """
    try:
        logger.debug(f"Serving GET /api/instances/{instance_id}")
        service, details = _find_instance(config, instance_id)
        if not details:
            return error(
                f"Instance '{instance_id}' not found",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )
        data = (
            details.model_dump(mode="python")
            if hasattr(details, "model_dump")
            else {"url": details.url, "api": details.api}
        )
        data = redact_secrets(data)
        data["name"] = instance_id
        data["service"] = service
        return ok(f"Instance '{instance_id}' retrieved", data)
    except Exception as e:
        logger.error(f"Error retrieving instance {instance_id}: {e}")
        return error(
            "Failed to retrieve instance", code="INSTANCE_GET_ERROR", status_code=500
        )


@router.post(
    "/instances/{instance_id}/test",
    summary="Test existing instance",
    description="Test connectivity and authentication for an existing configured instance.",
    responses={
        200: {
            "description": "Connection test successful",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Connection to main successful",
                        "data": {
                            "status_code": 200,
                            "response_time_ms": 45,
                        },
                    }
                }
            },
        },
        404: {"description": "Instance not found"},
        408: {"description": "Connection timeout"},
        502: {"description": "Connection failed"},
    },
)
def test_existing_instance(
    instance_id: str,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Test connectivity for an existing configured instance.

    Looks up the instance from configuration and tests that the URL
    and API credentials can successfully connect to the service.

    Args:
        instance_id: Name of the instance to test

    Returns:
        Connection test results with status code and response time
    """
    try:
        logger.debug(f"Serving POST /api/instances/{instance_id}/test")
        service, details = _find_instance(config, instance_id)
        if not details:
            return error(
                f"Instance '{instance_id}' not found",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )

        url = details.url.rstrip("/")
        api = details.api or ""

        if service == "plex":
            headers = {"X-Plex-Token": api} if api else {}
            test_url = f"{url}/library/sections"
        else:
            headers = {"X-Api-Key": api} if api else {}
            api_ver = "v1" if service == "lidarr" else "v3"
            test_url = f"{url}/api/{api_ver}/system/status"

        from backend.util.ssrf_guard import is_safe_url

        safe, reason = is_safe_url(test_url)
        if not safe:
            return error(
                f"URL refused: {reason}",
                code="URL_BLOCKED",
                status_code=400,
            )

        start = time.time()
        resp = requests.get(test_url, headers=headers, timeout=5, allow_redirects=False)
        elapsed = round((time.time() - start) * 1000)

        if resp.ok:
            return ok(
                f"Connection to {instance_id} successful",
                {"status_code": resp.status_code, "response_time_ms": elapsed},
            )
        return error(
            f"Connection failed: HTTP {resp.status_code}",
            code=f"HTTP_{resp.status_code}",
            status_code=resp.status_code,
        )
    except requests.exceptions.Timeout:
        return error("Connection timeout", code="CONNECTION_TIMEOUT", status_code=408)
    except requests.exceptions.ConnectionError:
        return error("Connection failed", code="CONNECTION_FAILED", status_code=502)
    except Exception as e:
        logger.error(f"Error testing instance {instance_id}: {e}")
        return error("Connection test failed", code="TEST_ERROR", status_code=500)


@router.get(
    "/instances/{instance_id}/stats",
    summary="Get instance statistics",
    description="Retrieve cached media counts + snapshot freshness for an instance.",
    responses={
        200: {
            "description": "Instance statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Stats for instance 'radarr_hd'",
                        "data": {
                            "instance": "radarr_hd",
                            "total_media": 150,
                            "snapshot_age_seconds": 320,
                        },
                    }
                }
            },
        }
    },
)
async def get_instance_stats(
    instance_id: str,
    service_type: str = Query(
        default=None, description="Service type: radarr, sonarr, lidarr, or plex"
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Retrieve cached media counts + snapshot freshness for an instance.

    For ARR instances (radarr/sonarr/lidarr): cached total row count +
    sync_state age. For Plex: plex_media_cache total + per-library breakdown +
    snapshot age. No live *arr calls — library-health counts (missing/upcoming)
    live on the Library Statistics page.

    Args:
        instance_id: Name of the instance to get statistics for
        service_type: Type of service (radarr, sonarr, lidarr, plex)

    Returns:
        Media counts appropriate to the service type
    """
    try:
        logger.debug(f"Serving GET /api/instances/{instance_id}/stats")

        if service_type == "plex":
            plex_media = db.plex.get_by_instance(instance_id) or []
            total = len(plex_media)

            # Count items per library
            libraries = {}
            for item in plex_media:
                lib = item.get("library_name", "Unknown")
                libraries[lib] = libraries.get(lib, 0) + 1

            # Age of the plex_media_cache snapshot for this instance. Every walk
            # re-upserts every item (bumping updated_at), so MAX(updated_at)
            # reliably reflects the last Plex walk — this is what the UI shows
            # as "Synced N ago" and what the TTL guard keys off.
            snapshot_age = db.plex.last_synced_age_seconds(instance_id)

            return ok(
                f"Stats for Plex instance '{instance_id}'",
                {
                    "instance": instance_id,
                    "total_media": total,
                    "libraries": libraries,
                    "snapshot_age_seconds": snapshot_age,
                },
            )
        else:
            # Count rows cheaply rather than loading the whole library to len()
            # it (a Lidarr instance is tens of thousands of rows).
            total = db.media.count_by_instance(instance_id)
            # ARR freshness comes from sync_state (written when the ARR sync
            # completes), not media_cache.updated_at — the latter only moves on
            # changed rows, so it would read "stale" right after a fresh sync of
            # an unchanged library.
            snapshot_age = (
                db.sync_state.age_seconds(service_type, instance_id)
                if service_type
                else None
            )
            # No live wanted/missing here — the Instances page doesn't show it,
            # and Library Statistics is the place for library-health counts. The
            # live per-instance *arr call was removed to keep this page light.
            return ok(
                f"Stats for instance '{instance_id}'",
                {
                    "instance": instance_id,
                    "total_media": total,
                    "snapshot_age_seconds": snapshot_age,
                },
            )
    except Exception as e:
        logger.error(f"Error retrieving stats for {instance_id}: {e}")
        return error(
            "Failed to retrieve instance stats",
            code="INSTANCE_STATS_ERROR",
            status_code=500,
        )


def _build_instance_payload(instance_id: str, config: ChubConfig) -> Optional[dict]:
    """Build the correct job payload based on instance type (ARR vs Plex)."""
    for svc_type in ("radarr", "sonarr", "lidarr"):
        if instance_id in getattr(config.instances, svc_type, {}):
            return {"arr_instances": [instance_id]}
    if instance_id in getattr(config.instances, "plex", {}):
        return {"plex_instances": [instance_id]}
    return None


@router.post(
    "/instances/{instance_id}/refresh",
    summary="Refresh instance data",
    description="Trigger a background cache refresh for a specific service instance.",
    responses={
        200: {
            "description": "Refresh job enqueued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Refresh initiated for 'radarr_hd'",
                        "data": {"job_id": 42},
                    }
                }
            },
        }
    },
)
async def refresh_instance(
    instance_id: str,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Trigger a background cache refresh for a specific instance.

    Enqueues a cache refresh job targeting only the specified instance.
    The job runs asynchronously in the background worker.

    Args:
        instance_id: Name of the instance to refresh

    Returns:
        Job ID for tracking the refresh operation
    """
    try:
        logger.debug(f"Serving POST /api/instances/{instance_id}/refresh")
        config = load_config()
        payload = _build_instance_payload(instance_id, config)
        if payload is None:
            return error(
                f"Instance '{instance_id}' not found in config",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )
        result = db.worker.enqueue_job("jobs", payload, job_type="cache_refresh")
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok(f"Refresh initiated for '{instance_id}'", {"job_id": job_id})
        return error("Error enqueuing refresh", code="REFRESH_ERROR", status_code=500)
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error refreshing instance {instance_id}: {e}")
        return error(
            "Failed to refresh instance", code="INSTANCE_REFRESH_ERROR", status_code=500
        )


@router.post(
    "/instances/{instance_id}/sync",
    summary="Sync instance data",
    description="Sync data for a specific service instance by triggering a cache refresh.",
    responses={
        200: {
            "description": "Sync job enqueued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Sync initiated for 'radarr_hd'",
                        "data": {"job_id": 43},
                    }
                }
            },
        }
    },
)
async def sync_instance(
    instance_id: str,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Sync data for a specific instance by triggering a cache refresh.

    Enqueues a cache refresh job targeting only the specified instance.
    Functionally equivalent to refresh but semantically represents
    a user-initiated sync operation.

    Args:
        instance_id: Name of the instance to sync

    Returns:
        Job ID for tracking the sync operation
    """
    try:
        logger.debug(f"Serving POST /api/instances/{instance_id}/sync")
        config = load_config()
        payload = _build_instance_payload(instance_id, config)
        if payload is None:
            return error(
                f"Instance '{instance_id}' not found in config",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )
        result = db.worker.enqueue_job("jobs", payload, job_type="cache_refresh")
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok(f"Sync initiated for '{instance_id}'", {"job_id": job_id})
        return error("Error enqueuing sync", code="SYNC_ERROR", status_code=500)
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error syncing instance {instance_id}: {e}")
        return error(
            "Failed to sync instance", code="INSTANCE_SYNC_ERROR", status_code=500
        )


@router.patch(
    "/instances/{instance_id}",
    summary="Toggle instance",
    description="Toggle the enabled state of a service instance.",
    responses={
        200: {
            "description": "Instance toggle result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instance toggle not yet implemented",
                        "data": {"status": "not_implemented"},
                    }
                }
            },
        }
    },
)
async def toggle_instance(
    instance_id: str,
    body: dict = None,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Toggle the enabled state of a service instance.

    Enables or disables the specified instance for automated
    processing. When disabled, the instance will be skipped
    during sync operations.

    Args:
        instance_id: Name of the instance to toggle
        body: Request body with 'enabled' boolean field

    Returns:
        Updated instance state
    """
    try:
        if body is None:
            body = {}

        enabled = body.get("enabled")
        if enabled is None:
            return error(
                "Missing 'enabled' field in request body",
                code="MISSING_FIELD",
                status_code=400,
            )

        if not isinstance(enabled, bool):
            return error(
                "'enabled' must be a boolean",
                code="INVALID_FIELD",
                status_code=400,
            )

        # Load current config
        config = load_config()

        # Find the instance across all service types
        service, details = _find_instance(config, instance_id)
        if not details:
            return error(
                f"Instance '{instance_id}' not found",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )

        # Update the enabled flag
        details.enabled = enabled

        # Save updated configuration
        save_config(config)
        plex_library_cache.invalidate()

        logger.info(
            f"Instance '{instance_id}' ({service}) {'enabled' if enabled else 'disabled'}"
        )
        return ok(
            f"Instance '{instance_id}' {'enabled' if enabled else 'disabled'}",
            {
                "name": instance_id,
                "service": service,
                "enabled": enabled,
            },
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to toggle instance {instance_id}: {e}")
        return error(
            "Failed to toggle instance",
            code="INSTANCE_TOGGLE_ERROR",
            status_code=500,
        )


@router.get(
    "/instances/{instance_id}/logs",
    summary="Get instance logs",
    description="Retrieve recent log entries for a specific service instance.",
    responses={
        200: {
            "description": "Instance logs retrieved",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Instance logs not yet available",
                        "data": {"logs": [], "status": "not_implemented"},
                    }
                }
            },
        }
    },
)
def get_instance_logs(
    instance_id: str,
    limit: int = Query(default=100, ge=1, le=5000),
    level: Optional[str] = Query(default=None),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve recent log entries for a specific service instance.

    Reads all log files from the unified logs directory and filters
    for lines containing the instance name. Supports filtering by
    log level and limiting the number of returned entries.

    Args:
        instance_id: Name of the instance to get logs for
        limit: Maximum number of log lines to return (default 100)
        level: Optional log level filter (info, error, debug, warning)

    Returns:
        List of filtered log entries for the instance
    """
    try:
        logger.debug(f"Serving GET /api/instances/{instance_id}/logs")

        if not os.path.exists(LOG_BASE_DIR):
            return ok(
                f"No logs found for instance '{instance_id}'",
                {"logs": [], "instance": instance_id},
            )

        # Collect all log lines from all module directories
        all_lines = []
        for module_name in os.listdir(LOG_BASE_DIR):
            module_path = os.path.join(LOG_BASE_DIR, module_name)
            if not os.path.isdir(module_path) or module_name == "debug":
                continue

            for filename in os.listdir(module_path):
                file_path = os.path.join(module_path, filename)
                if not os.path.isfile(file_path):
                    continue

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.rstrip("\n")
                            if not line:
                                continue
                            # Filter by instance name (case-insensitive)
                            if instance_id.lower() not in line.lower():
                                continue
                            # Filter by log level if specified
                            if level:
                                level_upper = level.upper()
                                if level_upper not in line.upper():
                                    continue
                            all_lines.append(line)
                except (PermissionError, OSError):
                    continue

        # Return the last N lines (most recent)
        filtered_lines = all_lines[-limit:]

        return ok(
            f"Found {len(filtered_lines)} log entries for instance '{instance_id}'",
            {"logs": filtered_lines, "instance": instance_id, "total": len(all_lines)},
        )

    except Exception as e:
        logger.error(f"Error retrieving logs for instance {instance_id}: {e}")
        return error(
            "Error retrieving instance logs",
            code="INSTANCE_LOGS_ERROR",
            status_code=500,
        )


@router.get(
    "/instances/{instance_id}/health",
    summary="Check single instance health",
    description="Check connectivity health of a specific configured service instance.",
    responses={
        200: {
            "description": "Health check result for the instance",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Health check for 'main'",
                        "data": {
                            "name": "main",
                            "service": "plex",
                            "status": "healthy",
                            "status_code": 200,
                            "response_time_ms": 45,
                        },
                    }
                }
            },
        },
        404: {"description": "Instance not found"},
    },
)
def check_instance_health(
    instance_id: str,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Check connectivity health of a single configured instance.

    Looks up the instance from configuration and tests connectivity,
    returning health status with response time. Uses the same logic
    as the bulk health check but for a single instance.

    Args:
        instance_id: Name of the instance to health-check

    Returns:
        Health status including connectivity state and response time
    """
    try:
        logger.debug(f"Serving GET /api/instances/{instance_id}/health")
        service, details = _find_instance(config, instance_id)
        if not details:
            return error(
                f"Instance '{instance_id}' not found",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )

        url = details.url.rstrip("/") if details.url else ""
        api = details.api or ""

        if service == "plex":
            headers = {"X-Plex-Token": api} if api else {}
            test_url = f"{url}/library/sections"
        else:
            headers = {"X-Api-Key": api} if api else {}
            api_ver = "v1" if service == "lidarr" else "v3"
            test_url = f"{url}/api/{api_ver}/system/status"

        from backend.util.ssrf_guard import is_safe_url

        safe, reason = is_safe_url(test_url)
        if not safe:
            return error(
                f"URL refused: {reason}",
                code="URL_BLOCKED",
                status_code=400,
            )

        start = time.time()
        try:
            resp = requests.get(
                test_url, headers=headers, timeout=2, allow_redirects=False
            )
            elapsed = round((time.time() - start) * 1000)
            health_data = {
                "name": instance_id,
                "service": service,
                "status": "healthy" if resp.ok else "unhealthy",
                "status_code": resp.status_code,
                "response_time_ms": elapsed,
            }
        except requests.exceptions.Timeout:
            health_data = {
                "name": instance_id,
                "service": service,
                "status": "timeout",
                "response_time_ms": 2000,
            }
        except requests.exceptions.ConnectionError:
            health_data = {
                "name": instance_id,
                "service": service,
                "status": "unreachable",
                "response_time_ms": 0,
            }
        except Exception as exc:
            logger.error(f"Health check failed for '{instance_id}': {exc}")
            health_data = {
                "name": instance_id,
                "service": service,
                "status": "error",
            }

        return ok(f"Health check for '{instance_id}'", health_data)
    except Exception as e:
        logger.error(f"Error checking health for {instance_id}: {e}")
        return error(
            "Failed to retrieve instance health",
            code="INSTANCE_HEALTH_ERROR",
            status_code=500,
        )

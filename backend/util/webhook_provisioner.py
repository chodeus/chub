"""Auto-provision CHUB's inbound poster webhook into Radarr/Sonarr.

Instead of the user hand-adding a Webhook connection in every *arr (Settings →
Connect → + → Webhook) and remembering to append ``?instance=``, CHUB writes the
connection for them via each arr's own ``/api/v3/notification`` API — the same
endpoints the arr UI drives (see :class:`backend.util.arr.BaseARRClient`).

Design notes:

- **Stateless.** CHUB persists NO provisioning state; the arr's own notification
  list is the source of truth. Idempotency + drift are a read-only GET + diff,
  matched by a fixed notification name (:data:`CHUB_NOTIFICATION_NAME`). Create
  if absent, PUT-in-place if drifted, no-op if identical — never delete+recreate
  (that would churn the id and drop any user edits), and never touch a
  differently-named webhook the user made themselves.
- **Secret rides in the URL, not a header.** The Webhook Connect type only
  reliably exposes url/method/username/password across arr versions, so the
  shared secret goes in ``?secret=`` (which CHUB already accepts) and the routing
  hint in ``?instance=<config name>`` — the two things the arr's payload can't be
  trusted to always carry.
- **Import-only triggers by default.** Only ``onDownload`` (On File Import) is
  enabled; that's the one phase that actually uploads to Plex. ``onUpgrade`` is an
  opt-in. The pre-download "added" triggers stay OFF (they can't upload — the item
  isn't in Plex yet).
- **Lidarr is skipped** — the poster endpoint can't process artist/album payloads.

Callers (backend/api/webhooks.py) resolve the arr-reachable base URL and pass it
in; this module never guesses it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from backend.util.arr import create_arr_client

# The fixed Connect name CHUB owns in each arr. Matching/creating by this exact
# (case-insensitive) name is what makes provisioning idempotent and keeps CHUB
# from ever touching a webhook the user created under a different name.
CHUB_NOTIFICATION_NAME = "CHUB Poster Sync"

_POSTER_ADD_PATH = "/api/webhooks/poster/add"


# ----- URL helpers --------------------------------------------------------


def normalize_base_url(base: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Validate/normalize the CHUB base URL to write into an arr.

    Returns ``(normalized, None)`` on success or ``(None, error_message)``. The
    URL must be an absolute http(s) URL and must not be localhost/loopback — an
    arr *container* can never reach CHUB at 127.0.0.1.
    """
    b = (base or "").strip().rstrip("/")
    if not b:
        return None, (
            "No CHUB base URL set. Enter the URL your *arr containers can reach "
            "CHUB at (e.g. http://192.168.1.10:8060 or https://chub.example.com)."
        )
    parsed = urlparse(b)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, (
            "Base URL must be an absolute http(s) URL, e.g. http://192.168.1.10:8060."
        )
    if (parsed.hostname or "").lower() in ("localhost", "127.0.0.1", "::1"):
        return None, (
            "Base URL can't be localhost/127.0.0.1 — an *arr container can't reach "
            "CHUB there. Use CHUB's LAN IP or its hostname."
        )
    return b, None


def build_webhook_url(base: str, instance_name: str, secret: Optional[str]) -> str:
    """The poster-webhook URL to write into an arr: base + ``/poster/add`` with
    ``?instance=<config name>`` (routing) and, if configured, ``&secret=``."""
    url = (
        f"{base.rstrip('/')}{_POSTER_ADD_PATH}"
        f"?instance={quote(str(instance_name), safe='')}"
    )
    if secret:
        url += f"&secret={quote(str(secret), safe='')}"
    return url


def _base_of(url: str) -> Optional[str]:
    """Return the ``scheme://host[:port]`` prefix of a URL, or None if it isn't a
    usable absolute http(s) URL. Used to recover a base URL from an existing
    webhook already configured in an arr."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    netloc = (
        parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"
    )
    return f"{parsed.scheme}://{netloc}"


# ----- notification body / diff -------------------------------------------


def _webhook_template(schema: Any) -> Optional[Dict[str, Any]]:
    """Find the 'Webhook' implementation template in a /notification/schema
    response so we use the arr's own field shape instead of hard-coding it."""
    if not isinstance(schema, list):
        return None
    for tmpl in schema:
        if isinstance(tmpl, dict) and tmpl.get("implementation") == "Webhook":
            return tmpl
    return None


def _field_value(notif: Dict[str, Any], name: str) -> Any:
    for field in notif.get("fields") or []:
        if isinstance(field, dict) and field.get("name") == name:
            return field.get("value")
    return None


def _added_trigger_key(instance_type: str) -> str:
    """The pre-download 'added' trigger flag differs by app."""
    return "onMovieAdded" if instance_type == "radarr" else "onSeriesAdd"


def desired_webhook_body(
    instance_type: str,
    url: str,
    schema: Any,
    include_upgrade: bool = False,
) -> Dict[str, Any]:
    """Build the notification body CHUB wants for this instance.

    Prefers the arr's own Webhook schema template (version-safe field names),
    falling back to the stable url/method fields. Triggers default to import-only
    (``onDownload``); ``onUpgrade`` is opt-in; every 'added'/grab/health trigger is
    forced OFF so provisioning is deterministic regardless of the template default.
    """
    template = _webhook_template(schema)
    if template:
        body = dict(template)
        fields = []
        for field in template.get("fields") or []:
            field = dict(field)
            if field.get("name") == "url":
                field["value"] = url
            elif field.get("name") == "method":
                field["value"] = 1  # POST
            fields.append(field)
        body["fields"] = fields
    else:
        body = {
            "implementation": "Webhook",
            "implementationName": "Webhook",
            "configContract": "WebhookSettings",
            "fields": [
                {"name": "url", "value": url},
                {"name": "method", "value": 1},
            ],
        }

    body["name"] = CHUB_NOTIFICATION_NAME
    body.setdefault("tags", [])
    # Import-only default. Everything else OFF (added events never upload to Plex).
    body["onGrab"] = False
    body["onDownload"] = True
    body["onUpgrade"] = bool(include_upgrade)
    body["onRename"] = False
    body["onHealthIssue"] = False
    body["onApplicationUpdate"] = False
    body[_added_trigger_key(instance_type)] = False
    return body


def diff_notification(
    current: Dict[str, Any], desired: Dict[str, Any], instance_type: str
) -> List[str]:
    """Named fields where the live notification differs from what CHUB wants.

    Only the fields CHUB manages: the target url (which carries ?instance= and
    ?secret=), the HTTP method, and the import/upgrade/added triggers. Empty list
    means the entry is already correct (a no-op update)."""
    drift: List[str] = []
    if _field_value(current, "url") != _field_value(desired, "url"):
        drift.append("url")
    cur_method, des_method = (
        _field_value(current, "method"),
        _field_value(desired, "method"),
    )
    if cur_method is not None and str(cur_method) != str(des_method):
        drift.append("method")
    for key in ("onDownload", "onUpgrade", _added_trigger_key(instance_type)):
        if bool(current.get(key)) != bool(desired.get(key)):
            drift.append(key)
    return drift


def _targets_poster_add(notif: Dict[str, Any]) -> bool:
    return _POSTER_ADD_PATH in str(_field_value(notif, "url") or "")


def _find_chub_notification(
    notifications: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for notif in notifications:
        if (notif.get("name") or "").strip().lower() == CHUB_NOTIFICATION_NAME.lower():
            return notif
    return None


def _save_failed_message(base_url: str) -> str:
    return (
        f"The *arr rejected the webhook — its connection test to {base_url} failed. "
        "Is CHUB reachable from the *arr container at that URL? Fix the base URL and "
        "retry, or use 'provision anyway' to skip the test."
    )


# ----- per-instance operations --------------------------------------------


def _base_result(instance_type: str, name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "type": instance_type,
        "status": "failed",
        "drift_fields": [],
        "action": None,
        "error": None,
        "foreign_webhook": None,
    }


def provision_instance(
    client: Any,
    instance_type: str,
    name: str,
    base_url: str,
    secret: Optional[str],
    *,
    include_upgrade: bool = False,
    dry_run: bool = False,
    force_save: bool = False,
) -> Dict[str, Any]:
    """Create/update CHUB's webhook in one arr (or, in dry_run, just report).

    Status is one of: ``connected`` (present & correct, or just created/updated),
    ``not_set_up`` (dry-run, no CHUB entry yet), ``drift`` (dry-run, present but
    stale), ``failed`` (unreachable or the arr rejected the save)."""
    result = _base_result(instance_type, name)
    try:
        existing = client.get_notifications()
        if existing is None:
            result["error"] = (
                "Couldn't read notifications from the instance (unreachable?)."
            )
            return result

        for notif in existing:
            if (
                notif.get("name") or ""
            ).strip().lower() != CHUB_NOTIFICATION_NAME.lower() and _targets_poster_add(
                notif
            ):
                result["foreign_webhook"] = notif.get("name")

        url = build_webhook_url(base_url, name, secret)
        desired = desired_webhook_body(
            instance_type, url, client.get_notification_schema(), include_upgrade
        )
        match = _find_chub_notification(existing)

        if match is None:
            if dry_run:
                result["status"] = "not_set_up"
                return result
            desired.pop("id", None)
            created = client.add_notification(desired, force_save=force_save)
            if isinstance(created, dict) and created.get("id"):
                result["status"], result["action"] = "connected", "created"
            else:
                result["error"] = _save_failed_message(base_url)
            return result

        drift = diff_notification(match, desired, instance_type)
        if not drift:
            result["status"], result["action"] = "connected", "noop"
            return result
        result["drift_fields"] = drift
        if dry_run:
            result["status"] = "drift"
            return result
        desired["id"] = match.get("id")
        updated = client.update_notification(
            match["id"], desired, force_save=force_save
        )
        if isinstance(updated, dict) and updated.get("id"):
            result["status"], result["action"] = "connected", "updated"
        else:
            result["error"] = _save_failed_message(base_url)
        return result
    except Exception as exc:  # noqa: BLE001 - surfaced per-instance, never fatal
        result["error"] = str(exc)
        return result


def deprovision_instance(
    client: Any, instance_type: str, name: str, *, dry_run: bool = False
) -> Dict[str, Any]:
    """Delete CHUB's own webhook from one arr. No-op if it isn't there."""
    result = _base_result(instance_type, name)
    try:
        existing = client.get_notifications()
        if existing is None:
            result["error"] = (
                "Couldn't read notifications from the instance (unreachable?)."
            )
            return result
        match = _find_chub_notification(existing)
        if match is None:
            result["status"], result["action"] = "not_set_up", "noop"
            return result
        if dry_run:
            result["status"] = "connected"
            return result
        if client.delete_notification(match["id"]):
            result["status"], result["action"] = "not_set_up", "removed"
        else:
            result["error"] = "The *arr rejected the delete."
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result


# ----- fleet operations ---------------------------------------------------


def _eligible_instances(
    config: Any, only: Optional[List[str]]
) -> Tuple[List[Tuple[str, str, str, str]], List[Dict[str, Any]]]:
    """Split configured instances into (eligible radarr/sonarr, skipped rows).

    ``only`` restricts to a set of instance names (case-insensitive). Lidarr and
    disabled/incomplete instances are returned as 'skipped' rows with a reason."""
    only_norm = {o.strip().lower() for o in only} if only else None
    eligible: List[Tuple[str, str, str, str]] = []
    skipped: List[Dict[str, Any]] = []

    instances = getattr(config, "instances", None)
    for bucket in ("radarr", "sonarr"):
        for name, info in (getattr(instances, bucket, {}) or {}).items():
            if only_norm is not None and name.strip().lower() not in only_norm:
                continue
            if getattr(info, "enabled", True) is False:
                row = _base_result(bucket, name)
                row["status"], row["error"] = "skipped", "Instance disabled."
                skipped.append(row)
                continue
            if not getattr(info, "url", None) or not getattr(info, "api", None):
                row = _base_result(bucket, name)
                row["status"], row["error"] = "skipped", "No URL/API key configured."
                skipped.append(row)
                continue
            eligible.append((bucket, name, info.url, info.api))

    for name, info in (getattr(instances, "lidarr", {}) or {}).items():
        if only_norm is not None and name.strip().lower() not in only_norm:
            continue
        row = _base_result("lidarr", name)
        row["status"] = "skipped"
        row["error"] = "Lidarr isn't supported by the poster webhook endpoint."
        skipped.append(row)

    return eligible, skipped


def _run_over_instances(
    eligible: List[Tuple[str, str, str, str]],
    op,
    logger: Any,
) -> List[Dict[str, Any]]:
    """Run ``op(client, type, name)`` per instance, concurrently, each with its
    own arr client that is always closed. A dead instance isolates to one row."""

    def _do(target: Tuple[str, str, str, str]) -> Dict[str, Any]:
        instance_type, name, url, api = target
        client = None
        try:
            client = create_arr_client(url, api, logger)
            if client is None or not client.is_connected():
                row = _base_result(instance_type, name)
                row["error"] = "Couldn't connect to the instance."
                return row
            return op(client, instance_type, name)
        except Exception as exc:  # noqa: BLE001
            row = _base_result(instance_type, name)
            row["error"] = str(exc)
            return row
        finally:
            session = getattr(client, "session", None)
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    if not eligible:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(eligible))) as pool:
        return list(pool.map(_do, eligible))


def provision_all(
    config: Any,
    base_url: str,
    secret: Optional[str],
    *,
    include_upgrade: bool = False,
    dry_run: bool = False,
    force_save: bool = False,
    only: Optional[List[str]] = None,
    logger: Any = None,
) -> List[Dict[str, Any]]:
    """Provision (or, in dry_run, report status for) every eligible instance."""
    eligible, skipped = _eligible_instances(config, only)

    def _op(client, instance_type, name):
        return provision_instance(
            client,
            instance_type,
            name,
            base_url,
            secret,
            include_upgrade=include_upgrade,
            dry_run=dry_run,
            force_save=force_save,
        )

    return _run_over_instances(eligible, _op, logger) + skipped


def deprovision_all(
    config: Any,
    *,
    dry_run: bool = False,
    only: Optional[List[str]] = None,
    logger: Any = None,
) -> List[Dict[str, Any]]:
    """Remove CHUB's webhook from every eligible instance (or the ``only`` set)."""
    eligible, skipped = _eligible_instances(config, only)

    def _op(client, instance_type, name):
        return deprovision_instance(client, instance_type, name, dry_run=dry_run)

    return _run_over_instances(eligible, _op, logger) + skipped


# ----- base-URL auto-detection --------------------------------------------


def detect_base_url(
    config: Any, *, only: Optional[List[str]] = None, logger: Any = None
) -> Optional[str]:
    """Best-effort auto-detect of CHUB's arr-reachable base URL.

    Reads each eligible arr's notifications and returns the base of the FIRST
    webhook already pointing at CHUB's ``/poster/add`` endpoint — CHUB's own from
    a prior run OR one the user configured by hand. This is the most reliable
    signal because such a URL demonstrably reaches CHUB (and, for a reverse-proxy
    or split-network setup, encodes the address the arr actually uses). Returns
    None when no arr has a matching webhook (e.g. a first-time setup)."""
    eligible, _ = _eligible_instances(config, only)
    if not eligible:
        return None

    def _probe(target: Tuple[str, str, str, str]) -> Optional[str]:
        _type, _name, url, api = target
        client = None
        try:
            client = create_arr_client(url, api, logger)
            if client is None or not client.is_connected():
                return None
            for notif in client.get_notifications() or []:
                candidate = str(_field_value(notif, "url") or "")
                if _POSTER_ADD_PATH in candidate:
                    return _base_of(candidate)
            return None
        except Exception:  # noqa: BLE001 - detection is best-effort, never fatal
            return None
        finally:
            session = getattr(client, "session", None)
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    with ThreadPoolExecutor(max_workers=min(8, len(eligible))) as pool:
        for found in pool.map(_probe, eligible):
            if found:
                return found
    return None


def resolve_base_url(
    config: Any,
    explicit: Optional[str] = None,
    *,
    origin_hint: Optional[str] = None,
    logger: Any = None,
) -> Tuple[Optional[str], str, Optional[str]]:
    """Resolve the arr-reachable base URL to use, returning
    ``(normalized, detected, error)``.

    Precedence: an ``explicit`` value the user typed → the saved
    ``general.public_url`` → a value auto-detected from an existing arr webhook →
    the browser ``origin_hint`` (last resort). Detection only runs when there's
    nothing more authoritative, so it doesn't add arr calls when a value is
    already known."""
    explicit = (explicit or "").strip()
    public_url = (
        getattr(getattr(config, "general", None), "public_url", "") or ""
    ).strip()
    detected = ""
    if not explicit and not public_url:
        detected = detect_base_url(config, logger=logger) or ""
    raw = explicit or public_url or detected or (origin_hint or "").strip()
    base_url, error = normalize_base_url(raw)
    return base_url, detected, error


def status_report(
    config: Any,
    secret: Optional[str],
    *,
    explicit: Optional[str] = None,
    origin_hint: Optional[str] = None,
    logger: Any = None,
) -> Dict[str, Any]:
    """Dry-run reconcile for the status endpoint: resolve the base URL (with
    auto-detection) and, unless the base URL is unusable, the per-instance status.
    Bundled into one call so all the arr I/O happens in a single off-loop hop."""
    base_url, detected, error = resolve_base_url(
        config, explicit, origin_hint=origin_hint, logger=logger
    )
    report: Dict[str, Any] = {
        "base_url": base_url or "",
        "detected_base_url": detected,
    }
    if error:
        report["base_url_error"] = error
        report["instances"] = []
    else:
        report["instances"] = provision_all(
            config, base_url, secret, dry_run=True, logger=logger
        )
    return report

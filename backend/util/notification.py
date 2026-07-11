import json
import logging
import threading
import time
import traceback
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from ratelimit import limits, sleep_and_retry

# Mirror of config.ALL_MODULES_SENTINEL — a destination whose `modules` list
# contains this reports on every module.
ALL_MODULES_SENTINEL = "__ALL__"


@dataclass
class NotifiarrConfig:
    webhook: str
    channel_id: int
    color: Optional[str] = None


@dataclass
class DiscordConfig:
    webhook: str
    bot_name: Optional[str] = None
    color: Optional[str] = None


class NotificationManager:
    def __init__(self, config, logger, module_name="main", format_module_name=None):
        self.config = config
        self.module_config = self._get_module_config(config, module_name)
        self.format_config = SimpleNamespace(
            module_name=format_module_name or module_name
        )
        self.logger = logger
        self.module_name = module_name
        self.SEND_HANDLERS = {
            "notifiarr": self.send_notifiarr_notification,
            "discord": self.send_discord_notification,
        }

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="python")
        return {}

    @classmethod
    def _get_module_config(cls, config: Any, module_name: str) -> Any:
        if not isinstance(config, dict) and hasattr(config, module_name):
            return getattr(config, module_name)
        if isinstance(config, dict):
            return config.get(module_name, config)
        return config

    def _iter_destinations(self) -> List[Dict[str, Any]]:
        """All configured destinations as plain dicts."""
        if isinstance(self.config, dict):
            raw_targets = self.config.get("notifications", {})
        else:
            raw_targets = getattr(self.config, "notifications", {})
        targets = self._as_dict(raw_targets)
        dests = targets.get("destinations")
        if isinstance(dests, list):
            return [self._as_dict(d) for d in dests]
        return []

    @staticmethod
    def _dest_matches_module(dest: Dict[str, Any], module_name: str) -> bool:
        mods = dest.get("modules")
        if not isinstance(mods, list):
            return False
        return ALL_MODULES_SENTINEL in mods or module_name in mods

    @staticmethod
    def _event_enabled(dest: Dict[str, Any], event: str) -> bool:
        events = dest.get("events")
        return bool(events.get(event, False)) if isinstance(events, dict) else False

    def _validate_target(
        self, method: str, cfg: Dict[str, Any]
    ) -> Union[str, Dict[str, Any]]:
        """Validate one destination's credentials. Returns a normalized config
        dict, or an ``"Invalid ..."`` string the caller can surface/log."""
        if not isinstance(cfg, dict):
            return f"Invalid config for {method}"
        if method == "discord":
            hook = str(cfg.get("webhook") or "").rstrip("/")
            # Require a real http(s) URL — rejects an empty webhook AND the
            # redacted "********" placeholder (no scheme), so a corrupted config
            # is skipped + logged rather than raising an SSRF error every run.
            if hook.startswith(("http://", "https://")):
                return {
                    "webhook": hook,
                    "bot_name": cfg.get("bot_name") or None,
                    "color": cfg.get("color") or None,
                }
            return "Invalid Discord configuration"
        if method == "notifiarr":
            hook = str(cfg.get("webhook") or "").rstrip("/")
            cid = cfg.get("channel_id")
            # channel_id can arrive as int or str (typed UI input vs hand-edited
            # yaml). Cast defensively — a non-numeric string here would otherwise
            # crash the whole notification dispatch with an unhandled ValueError.
            cid_int: Optional[int] = None
            if cid is not None:
                try:
                    cid_int = int(cid)
                except (TypeError, ValueError):
                    cid_int = None
            if hook.startswith(("http://", "https://")) and cid_int is not None:
                return {
                    "webhook": hook,
                    "channel_id": cid_int,
                    "color": cfg.get("color") or None,
                }
            return "Invalid Notifiarr configuration"
        return f"Invalid - Unknown notification type: {method}"

    def _resolve_targets(
        self, event: str, match_module: str
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Validated (method, config) pairs for enabled destinations whose
        `events` include ``event`` and whose module list covers
        ``match_module`` (directly or via the ``__ALL__`` sentinel)."""
        resolved: List[Tuple[str, Dict[str, Any]]] = []
        for dest in self._iter_destinations():
            if not dest.get("enabled", True):
                continue
            if not self._event_enabled(dest, event):
                continue
            if not self._dest_matches_module(dest, match_module):
                continue
            method = dest.get("method")
            validated = self._validate_target(method, dest.get("config") or {})
            if isinstance(validated, str):
                self.logger.warning(
                    "[Notification] skipping destination %s: %s",
                    dest.get("id") or dest.get("name") or method,
                    validated,
                )
                continue
            resolved.append((method, validated))
        return resolved

    @staticmethod
    def format_module_title(name: str) -> str:
        return name.replace("_", " ").title()

    @staticmethod
    def extract_error(resp: requests.Response) -> str:
        try:
            data = resp.json()
            return data.get("error", resp.text)
        except ValueError:
            return resp.text

    @staticmethod
    def resolve_color(
        output: Any,
        config_color: Optional[str],
        default: Union[int, str] = 0x00FF00,
    ) -> Union[int, str]:
        """Output-supplied color (e.g. red for errors) wins, then user's UI color, then default."""
        if isinstance(output, dict):
            out_color = output.get("color")
            if out_color is not None and out_color != "":
                return out_color
        if config_color:
            return config_color
        return default

    @staticmethod
    def build_notifiarr_payload(module_title: str, cid: int) -> Dict[str, Any]:
        # Notifiarr Passthrough has no documented field for overriding the
        # Discord bot username — the bot identity is controlled by the user's
        # Custom Bot setup on the Notifiarr side. CHUB's `bot_name` field is
        # therefore a CHUB-side label only for the Notifiarr service.
        return {
            "notification": {"update": False, "name": module_title, "event": "0"},
            "discord": {
                "color": "",
                "ping": {"pingUser": 0, "pingRole": 0},
                "images": {"thumbnail": "", "image": ""},
                "text": {
                    "title": "Test Notification",
                    "icon": "",
                    "content": "This is a test notification.",
                    "description": "This is a test notification.",
                    "fields": [],
                    "footer": "",
                },
                "ids": {"channel": cid},
            },
        }

    @staticmethod
    def build_discord_payload(
        module_title: str,
        data: Any,
        timestamp: str,
        dry_run: bool = False,
        color: Union[int, str] = 0x00FF00,
        bot_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if isinstance(color, str):
            try:
                color = int(color.lstrip("#"), 16)
            except ValueError:
                color = 0x00FF00  # malformed colour must not drop the notification
        payloads: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            data = [
                {
                    "embed": True,
                    "fields": fields,
                    "part": f" (Part {idx} of {len(data)})" if len(data) > 1 else "",
                }
                for idx, fields in data.items()
            ]
        for part in data:
            payload: Dict[str, Any] = {}
            if "embed" in part:
                payload["embeds"] = [
                    {
                        "title": f"{module_title} Notification{part.get('part', '')}",
                        "description": None,
                        "color": color,
                        "timestamp": timestamp,
                        "fields": part.get("fields", []),
                        "footer": {"text": "Powered by: CHUB"},
                    }
                ]
            if "content" in part:
                payload["content"] = (
                    f"__**Dry Run**__\n{part['content']}"
                    if dry_run
                    else part["content"]
                )
            elif dry_run:
                payload["content"] = "__**Dry Run**__"
            payload["username"] = bot_name or "Notification Bot"
            payloads.append(payload)
        return payloads

    @staticmethod
    @sleep_and_retry
    @limits(calls=5, period=5)
    def safe_post(url: str, payload: Dict[str, Any]) -> requests.Response:
        # Webhook URLs come from admin config, but guard them like every
        # other outbound fetch — a misconfigured URL must not become a probe
        # of link-local/metadata services.
        from backend.util.ssrf_guard import is_safe_url

        safe, reason = is_safe_url(url)
        if not safe:
            raise ValueError(f"Notification URL blocked by SSRF guard: {reason}")
        # A hung webhook must not stall the whole run: bound every POST.
        return requests.post(url, json=payload, timeout=15)

    # How many times a single message is re-sent after a 429 before giving up.
    _MAX_RATE_LIMIT_RETRIES = 5

    @staticmethod
    def _retry_after_seconds(resp: requests.Response) -> float:
        """Seconds to wait before retrying a 429, taken from Discord's
        authoritative ``retry_after`` JSON field (seconds, float) and falling
        back to the standard ``Retry-After`` header. A small buffer is added and
        the value is clamped so a bogus/global limit can't stall the worker for
        minutes.
        """
        wait: Optional[float] = None
        try:
            body = resp.json()
            if isinstance(body, dict) and body.get("retry_after") is not None:
                wait = float(body["retry_after"])
        except Exception:
            wait = None
        if wait is None:
            headers = getattr(resp, "headers", None) or {}
            raw = headers.get("Retry-After") or headers.get("retry-after")
            if raw is not None:
                try:
                    wait = float(raw)
                except (TypeError, ValueError):
                    wait = None
        if wait is None:
            wait = 1.0
        return max(0.0, min(wait, 30.0)) + 0.25

    def send_and_log_response(
        self, label: str, hook: str, payload: Dict[str, Any]
    ) -> Tuple[bool, str]:
        try:
            resp = self.safe_post(hook, payload)
            # Discord/Notifiarr rate-limit (429) responses carry the exact wait
            # in `retry_after`. Honour it and re-send the SAME message instead of
            # dropping it — bulk runs used to lose every rate-limited part and
            # spam the log with 429 errors.
            attempts = 0
            while resp.status_code == 429 and attempts < self._MAX_RATE_LIMIT_RETRIES:
                attempts += 1
                wait = self._retry_after_seconds(resp)
                self.logger.warning(
                    f"[Notification] {label} rate-limited (429); retry "
                    f"{attempts}/{self._MAX_RATE_LIMIT_RETRIES} in {wait:.2f}s"
                )
                time.sleep(wait)
                resp = self.safe_post(hook, payload)
            if resp.status_code not in (200, 204):
                err = self.format_notification_error(resp, label)
                self.logger.error(
                    f"[Notification] ❌ {label} failed ({resp.status_code}): {err}"
                )
                self.logger.debug(f"Failed payload:\n{json.dumps(payload, indent=2)}")
                return False, err
            else:
                self.logger.info(f"[Notification] ✅ {label} notification sent.")
                return True, "Notification sent successfully."
        except Exception as e:
            tb_str = traceback.format_exc()
            self.logger.error(
                f"[Notification] {label} send exception: {e}\n{tb_str}", exc_info=True
            )
            return False, f"{e}\n{tb_str}"

    def send_notifiarr_notification(
        self,
        auth_data: NotifiarrConfig,
        module_title: str,
        output: Any,
        test: bool = False,
    ) -> Tuple[bool, str]:
        hook = auth_data.webhook.rstrip("/")
        cid = auth_data.channel_id
        payload = self.build_notifiarr_payload(module_title, cid)
        if test:
            resp = self.safe_post(hook, payload)
            success = resp.status_code in (200, 204)
            msg = (
                "Test notification sent via Notifiarr."
                if success
                else f"Notifiarr Test failed ({resp.status_code}): {self.extract_error(resp)}"
            )
            return success, msg

        from backend.util.notification_formatting import format_for_discord

        data, _ = format_for_discord(self.format_config, output)
        parts: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            for idx, fields in data.items():
                parts.append(
                    {
                        "embed": True,
                        "fields": fields,
                        "part": (
                            f" (Part {idx} of {len(data)})" if len(data) > 1 else ""
                        ),
                    }
                )
        else:
            parts = data
        for part in parts:
            pt_payload = {
                "notification": {"update": False, "name": module_title, "event": ""},
                "discord": {
                    "color": "",
                    "ping": {"pingUser": 0, "pingRole": 0},
                    "images": {"thumbnail": "", "image": ""},
                    "ids": {"channel": cid},
                },
            }
            if part.get("embed"):
                fields = [
                    {
                        "title": f.get("name", ""),
                        "text": f.get("value", ""),
                        "inline": bool(f.get("inline", False)),
                    }
                    for f in part.get("fields", [])
                ]
                pt_payload["discord"]["text"] = {
                    "title": f"{module_title} Notification{part.get('part', '')}",
                    "fields": fields,
                }
            else:
                content = part.get("content")
                pt_payload["discord"]["text"] = {
                    "description": " ",
                    "content": content,
                }
            color = self.resolve_color(output, auth_data.color, default="00FF00")
            if isinstance(color, int):
                color = f"{color:06X}"
            elif isinstance(color, str):
                color = color.lstrip("#")
            pt_payload["discord"]["color"] = color
            self.send_and_log_response("Notifiarr", hook, pt_payload)
        return True, "Notification sent to Notifiarr."

    def send_discord_notification(
        self,
        auth_data: DiscordConfig,
        module_title: str,
        output: Any,
        test: bool = False,
    ) -> Tuple[bool, str]:
        from datetime import datetime

        from backend.util.notification_formatting import format_for_discord

        hook = auth_data.webhook.rstrip("/")
        bot_name = auth_data.bot_name
        timestamp = datetime.utcnow().isoformat()
        color = self.resolve_color(output, auth_data.color, default=0x00FF00)

        if test:
            data = [
                {
                    "embed": True,
                    "fields": [
                        {
                            "name": "Test Notification",
                            "value": "This is a test notification from CHUB.",
                        }
                    ],
                }
            ]
            dry_run = False
        else:
            data, _ = format_for_discord(self.format_config, output)
            dry_run = getattr(self.module_config, "dry_run", False)

        success = True
        messages = []
        for payload in self.build_discord_payload(
            module_title,
            data,
            timestamp,
            dry_run=dry_run,
            color=color,
            bot_name=bot_name,
        ):
            ok, msg = self.send_and_log_response("Discord", hook, payload)
            if not ok:
                success = False
            messages.append(msg)
        return success, "; ".join(messages)

    def send_notification(
        self, output: Any, event: str = "success", match_module: Optional[str] = None
    ) -> Dict[str, Any]:
        """Dispatch to every enabled destination that reports on ``match_module``
        (defaults to this manager's module) for the given ``event``
        ("success" | "failure"). Returns a standardized result."""
        results = []
        module = match_module or self.module_name
        module_title = self.format_module_title(self.module_name)
        for method, data in self._resolve_targets(event, module):
            entry = {"type": method, "ok": False, "message": None, "error": None}
            handler = self.SEND_HANDLERS.get(method)
            try:
                if handler:
                    if method == "notifiarr":
                        cfg = NotifiarrConfig(**data)
                        ok, msg = handler(cfg, module_title, output)
                    elif method == "discord":
                        cfg = DiscordConfig(**data)
                        ok, msg = handler(cfg, module_title, output)
                    else:
                        ok, msg = False, f"Unknown handler for {method}"
                    entry["ok"] = ok
                    entry["message"] = msg
                    if not ok:
                        entry["error"] = msg
                else:
                    entry["error"] = f"Unknown notification target: {method}"
                results.append(entry)
            except Exception as ex:
                tb_str = traceback.format_exc()
                entry["error"] = f"Exception for {method}: {ex}\n{tb_str}"
                results.append(entry)
                self.logger.error(
                    f"Exception for {method}: {ex}\n{tb_str}", exc_info=True
                )
        success = any(r.get("ok") for r in results)
        out = {"success": success, "results": results}
        if not success:
            errors = [r.get("error") for r in results if r.get("error")]
            out["error"] = "; ".join(errors)
        return out

    def send_test_to(self, method: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Send a single test notification for one method + credentials. Used by
        the API test button — bypasses the enabled/event/module filtering."""
        module_title = self.format_module_title(self.module_name)
        entry: Dict[str, Any] = {
            "type": method,
            "ok": False,
            "message": None,
            "error": None,
        }
        validated = self._validate_target(method, config)
        if isinstance(validated, str):
            entry["message"] = validated
            entry["error"] = validated
            return {"success": False, "results": [entry], "error": validated}
        try:
            if method == "notifiarr":
                cfg = NotifiarrConfig(**validated)
                ok, msg = self.send_notifiarr_notification(
                    cfg, module_title, None, test=True
                )
            elif method == "discord":
                cfg = DiscordConfig(**validated)
                ok, msg = self.send_discord_notification(
                    cfg, module_title, None, test=True
                )
            else:
                ok, msg = False, f"Unknown notification target: {method}"
            entry["ok"] = ok
            entry["message"] = msg
            if not ok:
                entry["error"] = msg
        except Exception as ex:
            tb_str = traceback.format_exc()
            entry["message"] = f"Exception while testing {method}: {ex}\n{tb_str}"
            entry["error"] = f"{ex}\n{tb_str}"
        out: Dict[str, Any] = {"success": bool(entry["ok"]), "results": [entry]}
        if not entry["ok"]:
            out["error"] = entry["error"] or entry["message"]
        return out

    def format_notification_error(
        self, source: Any, label: str = "", config: Any = None
    ) -> str:
        if isinstance(source, requests.Response):
            return self.extract_error(source)
        return f"{label} unknown error"


class ErrorNotifyHandler(logging.Handler):
    """Custom logging handler to send errors to Discord/Notifiarr via notifications.

    Dispatches the "failure" event to destinations that report on the failing
    module (matched by the record's `source_module`, or `__ALL__`), rendering via
    the `error_notify` formatter. Uses a thread-local re-entry guard so log calls
    made by the notification machinery itself don't recursively trigger more
    notifications.
    """

    _reentry = threading.local()

    def __init__(self, config, module_name="main", logger=None):
        super().__init__(level=logging.ERROR)
        self.manager = NotificationManager(
            config, logger, module_name, format_module_name="error_notify"
        )

    def emit(self, record):
        if getattr(ErrorNotifyHandler._reentry, "active", False):
            return
        # The notification dispatch path itself logs at ERROR on failure; ignore
        # records originating from it to avoid feedback loops independent of the
        # thread-local guard (e.g. a different thread reading the same logger).
        if record.name == "chub.notification" or "notification" in (
            getattr(record, "module", "") or ""
        ):
            return
        ErrorNotifyHandler._reentry.active = True
        try:
            msg = record.getMessage()
            tb = None
            error_type_msg = ""
            if record.exc_info:
                tb_lines = traceback.format_exception(*record.exc_info)
                tb = "".join(tb_lines)
                if tb_lines:
                    error_type_msg = tb_lines[-1].strip()
            elif record.stack_info:
                tb = record.stack_info

            error_msg = f"{msg}\n{error_type_msg}" if error_type_msg else msg

            # The redaction filter never sees the exception text/traceback, so
            # scrub secrets (e.g. tokens in a request URL) before they leave.
            from backend.util.logger import SmartRedactionFilter

            error_msg = SmartRedactionFilter.redact(error_msg)
            if tb:
                tb = SmartRedactionFilter.redact(tb)

            source_module = getattr(record, "module", None) or self.manager.module_name
            output = {
                "error_message": error_msg,
                "traceback": tb,
                "color": "FF0000",
                "source_module": source_module,
            }

            self.manager.send_notification(
                output, event="failure", match_module=source_module
            )
        except Exception as e:
            if self.manager.logger:
                self.manager.logger.error(
                    f"[ErrorNotifyHandler] Failed to send error notification: {e}",
                    exc_info=True,
                )
        finally:
            ErrorNotifyHandler._reentry.active = False


def install_error_notify_handler(config, logger=None) -> Optional[ErrorNotifyHandler]:
    """Attach ErrorNotifyHandler to the root logger if any enabled destination
    reports on failures.

    Returns the handler instance (or None if not installed). Safe to call multiple
    times — subsequent calls are no-ops once a handler is attached.
    """
    root = logging.getLogger()
    for existing in root.handlers:
        if isinstance(existing, ErrorNotifyHandler):
            return existing

    raw = getattr(config, "notifications", None)
    if raw is not None and hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="python")
    destinations = raw.get("destinations") if isinstance(raw, dict) else None

    has_failure_target = False
    if isinstance(destinations, list):
        for dest in destinations:
            if hasattr(dest, "model_dump"):
                dest = dest.model_dump(mode="python")
            if not isinstance(dest, dict):
                continue
            events = dest.get("events")
            if (
                dest.get("enabled", True)
                and isinstance(events, dict)
                and events.get("failure")
            ):
                has_failure_target = True
                break

    if not has_failure_target:
        return None

    handler = ErrorNotifyHandler(config, module_name="main", logger=logger)
    root.addHandler(handler)
    return handler


def refresh_error_notify_handler(config, logger=None) -> Optional["ErrorNotifyHandler"]:
    """Re-evaluate the handler against current config on reload: drop the old one
    (stale snapshot) and re-install if a failure destination is now configured —
    so changes take effect without a restart."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, ErrorNotifyHandler):
            root.removeHandler(existing)
    return install_error_notify_handler(config, logger=logger)

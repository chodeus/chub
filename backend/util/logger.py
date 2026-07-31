import logging
import os
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from backend.util.helper import create_bar
from backend.util.version import get_version

# Size cap per log file. Rotation otherwise only ran on the first Logger() per
# process, so a hot error loop could grow one file without bound (a 401 retry
# storm once wrote 296MB / 2.4M lines). 0 disables the cap.
DEFAULT_MAX_LOG_BYTES = 10 * 1024 * 1024


def _max_log_bytes() -> int:
    # A negative value must NOT collapse to 0 — 0 is the documented "no cap"
    # opt-out, so that would silently restore unbounded growth.
    try:
        value = int(os.getenv("LOG_MAX_BYTES", "").strip() or DEFAULT_MAX_LOG_BYTES)
    except ValueError:
        return DEFAULT_MAX_LOG_BYTES
    return value if value >= 0 else DEFAULT_MAX_LOG_BYTES


def rotation_namer(default_name: str) -> str:
    """Map RotatingFileHandler's `<base>.log.N` onto this app's `<base>.N.log`.
    prune_old_logs() and the log viewer both glob `*.log`, which the default
    naming would escape entirely."""
    base, _, index = default_name.rpartition(".")
    if not index.isdigit():
        return default_name
    return f"{base.rsplit('.log', 1)[0]}.{index}.log"


class SafeFormatter(logging.Formatter):
    """Formatter that sets the source tag and redacts secrets from the FULL
    rendered line — including the exc_info traceback, which the record-level
    filter (msg/args only) never sees, so a secret embedded in an exception
    (e.g. a Plex/Notifiarr URL) would otherwise leak to the log verbatim."""

    def format(self, record):
        source = getattr(record, "source", None)
        record.source_tag = f"[{source}]" if source else ""
        # Buffered module logs (see _BufferingLogger) replay at the end of a run;
        # without this every line of a 49-minute run reads as the flush time.
        # super().format() recomputes asctime from created.
        orig_created = getattr(record, "orig_created", None)
        if orig_created is not None:
            record.created = orig_created
        return SmartRedactionFilter.redact(super().format(record))


class SmartRedactionFilter(logging.Filter):
    """
    Improved redaction filter that's less aggressive and more targeted.
    Focuses on actual sensitive data rather than everything that looks like it might be.
    """

    @staticmethod
    def redact(text: str) -> str:
        """Apply smart redaction to text, preserving legitimate data."""
        if not isinstance(text, str):
            return text

        # More targeted redaction patterns.
        # Each pattern balances precision (avoid redacting legitimate data like
        # filenames or IDs) with coverage. Minimum lengths are chosen so we catch
        # real API keys while leaving short IDs, UUID fragments, and file hashes alone.
        patterns = [
            # Discord webhooks - very specific pattern
            (
                r"https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]{60,}",
                "https://discord.com/api/webhooks/[redacted]",
            ),
            # Google OAuth client IDs
            (
                r"\b\d{10,}-[a-zA-Z0-9]{20,}\.apps\.googleusercontent\.com\b",
                "[redacted].apps.googleusercontent.com",
            ),
            # Google OAuth client secrets
            (r"GOCSPX-[A-Za-z0-9_-]{20,}", "GOCSPX-[redacted]"),
            # JWT tokens (three base64url segments separated by dots)
            (
                r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
                "[redacted-jwt]",
            ),
            # AWS-style access keys
            (r"\bAKIA[0-9A-Z]{16}\b", "[redacted-aws-key]"),
            # GitHub tokens
            (r"\bghp_[A-Za-z0-9]{30,}\b", "[redacted-gh-token]"),
            (r"\bgho_[A-Za-z0-9]{30,}\b", "[redacted-gh-token]"),
            # bcrypt hashes ($2a$/$2b$/$2y$)
            (r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", "[redacted-bcrypt]"),
            # JSON field redaction
            (r'("refresh_token":\s*")[^"]{20,}(")', r"\1[redacted]\2"),
            (r'("access_token":\s*")[^"]{20,}(")', r"\1[redacted]\2"),
            (r'("client_secret":\s*")[^"]{20,}(")', r"\1[redacted]\2"),
            (r'("jwt_secret":\s*")[^"]{20,}(")', r"\1[redacted]\2"),
            (r'("password_hash":\s*")[^"]{20,}(")', r"\1[redacted]\2"),
            (r'("webhook_secret":\s*")[^"]+(")', r"\1[redacted]\2"),
            (r'("X-Api-Key":\s*")[^"]{8,}(")', r"\1[redacted]\2"),
            (r'("X-Plex-Token":\s*")[^"]{8,}(")', r"\1[redacted]\2"),
            # Configuration field redaction (yaml/kv forms)
            (
                r"client_secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?",
                "client_secret: [redacted]",
            ),
            (
                r"jwt_secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?",
                "jwt_secret: [redacted]",
            ),
            (
                r"webhook_secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]+['\"]?",
                "webhook_secret: [redacted]",
            ),
            # OAuth tokens in yaml/unquoted key:value form (e.g. a dumped
            # SyncGDriveToken: `access_token: ya29...`). The JSON-quoted rules
            # above only match the `"access_token": "..."` form.
            (
                r"(access_token|refresh_token|token)\s*[:=]\s*['\"]?[A-Za-z0-9._\-/~+]{20,}['\"]?",
                r"\1: [redacted]",
            ),
            (r"webhook\s*[:=]\s*['\"]?https://[^'\"\s]+['\"]?", "webhook: [redacted]"),
            # API keys - short form keys (min 16) plus legacy long form (32+)
            (
                r"\bapi(?:_?key)?\s*[:=]\s*['\"]?[A-Za-z0-9]{16,}['\"]?",
                "api: [redacted]",
            ),
            # Bearer tokens in Authorization headers
            (
                r"(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._\-]{16,}",
                r"\1[redacted]",
            ),
            # Passwords
            (r"password\s*[:=]\s*['\"]?[^\s'\"]{8,}['\"]?", "password: [redacted]"),
            # Secrets in URL query parameters — requests exceptions embed the
            # full URL, and the JSON/config patterns above only match quoted
            # or key: value forms, not ?key=value.
            (
                r"([?&](?:x-plex-token|client_key|access_token|refresh_token|token|secret)=)[^&\s'\"]+",
                r"\1[redacted]",
            ),
            # Notifiarr passthrough API key lives in the URL PATH, not a query
            # param, so the rule above misses it (exceptions embed the full URL).
            (
                r"(notifiarr\.com/api/v\d+/notification/passthrough/)[A-Za-z0-9_\-]{8,}",
                r"\1[redacted]",
            ),
        ]

        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    def filter(self, record):
        """Apply redaction to log record."""
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = self.redact(record.msg)
        if hasattr(record, "args") and record.args:
            record.args = tuple(self.redact(str(arg)) for arg in record.args)
        return True


class Logger:
    """
    Enhanced logger with smart redaction, automatic log rotation, and cleaner initialization.
    """

    _initialized = set()

    @staticmethod
    def redact_sensitive_info(text: str) -> str:
        return SmartRedactionFilter.redact(text)

    def __init__(
        self,
        log_level: str,
        module_name: str,
        max_logs: int = 9,
        retention_days: Optional[int] = None,
        extra: Optional[dict] = None,
    ):
        """
        Initialize logger with enhanced features.

        Args:
            log_level: Logging level (DEBUG, INFO, etc.)
            module_name: Name of the module for log organization
            max_logs: Number of rotated logs to keep (defaults to 9 if not provided)
            retention_days: (deprecated; ignored) kept for backward compatibility
            extra: Extra context for log adapters
        """
        log_level = log_level.upper()
        self.module_name = module_name
        self._extra = extra or {}
        self.retention_days = retention_days

        env_log_file = os.getenv("LOG_FILE", "").strip()
        if env_log_file:
            log_file_path = env_log_file
        else:
            log_file_path = self._get_log_file_path(module_name)

        key = (module_name, log_file_path)
        already_initialized = key in Logger._initialized

        self._logger = logging.getLogger(module_name)
        # Stamp start_time on every instantiation — log_outro() uses
        # `datetime.now() - start_time` to print "Run Time:", and the
        # _initialized cache below short-circuits the handler/rotation
        # setup so without this hoist the second-and-later runs in a
        # long-lived process would print elapsed time since first init.
        self.start_time = datetime.now()
        self._logger.start_time = self.start_time

        if already_initialized:
            return
        Logger._initialized.add(key)

        # Setup log directory and rotation
        self._setup_log_directory_and_rotation(log_file_path, max_logs)

        self._logger.setLevel(getattr(logging, log_level, logging.INFO))

        # Attach this module's own file handler if it doesn't have one yet.
        # Check the logger's OWN handlers, NOT hasHandlers() — the latter is true
        # when any ancestor (the root logger) has a handler, e.g. once the
        # failure-notification ErrorNotifyHandler is installed on root. That made
        # a module logger first created at run time (extensions like
        # poster_self_heal) skip its file handler, so its run logs only
        # propagated to root and never reached <module>.log.
        if not self._logger.handlers:
            self._setup_handlers(log_file_path, max_logs)

        # Log startup message
        version = get_version()
        self._logger.info(
            create_bar(f"{module_name.replace('_', ' ').upper()} Version: {version}")
        )

    def _get_log_file_path(self, module_name: str) -> str:
        """Determine the log file path for a module."""
        log_base = os.getenv("LOG_DIR")
        if log_base:
            log_dir = Path(log_base) / module_name
        else:
            log_dir = Path(__file__).resolve().parents[2] / "logs" / module_name

        log_dir.mkdir(parents=True, exist_ok=True)
        return str(log_dir / f"{module_name}.log")

    def _setup_log_directory_and_rotation(
        self, log_file_path: str, max_logs: int
    ) -> None:
        """Setup log directory and handle rotation with consistent naming pattern."""
        log_dir = os.path.dirname(log_file_path)
        os.makedirs(log_dir, exist_ok=True)

        # Only rotate if main log file exists
        if os.path.isfile(log_file_path):
            # Extract base name (without .log extension)
            base_name = log_file_path.rsplit(".log", 1)[0]

            # Shift existing numbered logs: module_name.9.log -> module_name.10.log, etc.
            for i in range(max_logs - 1, 0, -1):
                old_file = f"{base_name}.{i}.log"
                new_file = f"{base_name}.{i + 1}.log"
                if os.path.exists(old_file):
                    os.rename(old_file, new_file)

            # Move current log to module_name.1.log
            rotated_file = f"{base_name}.1.log"
            os.rename(log_file_path, rotated_file)

    def _setup_handlers(self, log_file_path: str, max_logs: int) -> None:
        """Setup logging handlers with improved redaction."""
        formatter = SafeFormatter(
            fmt="%(asctime)s %(levelname)s %(source_tag)s[%(filename)s]: %(message)s",
            datefmt="%d/%m/%Y %H:%M:%S",
        )
        redaction_filter = SmartRedactionFilter()

        # File handler. maxBytes must be non-zero or doRollover() never fires.
        file_handler = RotatingFileHandler(
            log_file_path,
            mode="a",
            maxBytes=_max_log_bytes(),
            backupCount=max_logs,
        )
        file_handler.namer = rotation_namer
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction_filter)
        self._logger.addHandler(file_handler)

        # Console handler for general module or when LOG_TO_CONSOLE is set
        should_log_to_console = self.module_name == "general" or os.environ.get(
            "LOG_TO_CONSOLE", ""
        ).lower() in ("1", "true", "yes")

        if should_log_to_console:
            console = logging.StreamHandler()
            # Console (container stdout) level is independent of the file level so
            # you can keep verbose DEBUG in the per-module files while the
            # container log stays clean: set CONSOLE_LOG_LEVEL=INFO. Unset → matches
            # the logger's own level (previous behaviour).
            console_level = os.getenv("CONSOLE_LOG_LEVEL", "").strip().upper()
            console.setLevel(
                getattr(logging, console_level, self._logger.level)
                if console_level
                else self._logger.level
            )
            console.addFilter(lambda record: record.levelno < logging.ERROR)
            console.setFormatter(SafeFormatter("%(message)s"))
            console.addFilter(redaction_filter)
            self._logger.addHandler(console)

        # Error console handler (always present for errors)
        error_console = logging.StreamHandler()
        error_console.setLevel(logging.ERROR)
        error_console.setFormatter(
            SafeFormatter(f"%(levelname)s [{self.module_name.upper()}]: %(message)s")
        )
        error_console.addFilter(redaction_filter)
        self._logger.addHandler(error_console)

    def get_adapter(self, extra=None):
        """
        Get a logger adapter with additional context.

        Args:
            extra: Additional context (string for source, or dict for multiple fields)

        Returns:
            ChubLoggerAdapter with enhanced context
        """
        new_extra = dict(self._extra)
        if extra:
            if isinstance(extra, str):
                new_extra["source"] = extra.upper()
            elif isinstance(extra, dict):
                new_extra.update(extra)
            else:
                raise ValueError(
                    "ChubLoggerAdapter.get_adapter() expects a string or dict"
                )

        new_extra["source"] = (new_extra.get("source") or self.module_name).upper()
        return ChubLoggerAdapter(self._logger, new_extra)

    def log_outro(self) -> None:
        """Log completion message with runtime information."""
        start = getattr(self, "start_time", None)
        if start is None:
            return

        duration = datetime.now() - start
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_duration = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        module_name = self._logger.name.replace("_", " ").upper()
        self._logger.info(create_bar(f"{module_name} | Run Time: {formatted_duration}"))

    def __getattr__(self, name):
        """Delegate unknown attributes to the underlying logger."""
        return getattr(self._logger, name)


class ChubLoggerAdapter(logging.LoggerAdapter):
    """Enhanced logger adapter with better context management."""

    def log_outro(self) -> None:
        """Delegate log_outro to the underlying Logger if available."""
        # Walk up the chain: self.logger may be a stdlib Logger that was
        # created by our Logger class, which stashes start_time on it.
        underlying = self.logger
        start_time = getattr(underlying, "start_time", None)
        if start_time is None:
            return

        from datetime import datetime

        duration = datetime.now() - start_time
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_duration = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        module_name = underlying.name.replace("_", " ").upper()

        from backend.util.helper import create_bar  # noqa: E402 — lazy import to break circular dependency

        underlying.info(create_bar(f"{module_name} | Run Time: {formatted_duration}"))

    def get_adapter(self, extra=None):
        """
        Get a new adapter with additional context.

        Args:
            extra: Additional context (string for source, or dict for multiple fields)

        Returns:
            New ChubLoggerAdapter with enhanced context
        """
        new_extra = dict(self.extra)
        if extra:
            if isinstance(extra, str):
                new_extra["source"] = extra.upper()
            elif isinstance(extra, dict):
                new_extra.update(extra)
            else:
                raise ValueError(
                    "ChubLoggerAdapter.get_adapter() expects a string or dict"
                )

        new_extra["source"] = (new_extra.get("source") or self.logger.name).upper()
        return ChubLoggerAdapter(self.logger, new_extra)

    def heartbeat(self, msg, *args, **kwargs) -> None:
        """Emit a repetitive-by-design progress line.

        Lives at INFO level so users who explicitly want to see progress
        (e.g. log_level=info + Hide-Heartbeat toggle off) can. The frontend
        Logs page filters lines starting with the [hb] marker out of the
        default view via the Hide-Heartbeat toggle, so noisy heartbeats
        don't drown the meaningful log.

        Use for: per-second progress ticks, per-item loop heartbeats, any
        line that fires N times during a single run with no specific
        new information per invocation beyond an incremented counter.
        """
        self.info(f"[hb] {msg}", *args, **kwargs)


def ensure_log_dir_and_rotate(log_file_path: str, max_logs: int = 9) -> None:
    """
    Ensures consistent <module_name>.#.log naming pattern.

    Args:
        log_file_path: Path to the main log file
        max_logs: Maximum number of rotated logs to keep
    """
    log_dir = os.path.dirname(log_file_path)
    os.makedirs(log_dir, exist_ok=True)

    # Only rotate if main log file exists
    if os.path.isfile(log_file_path):
        # Extract base name (without .log extension)
        base_name = log_file_path.rsplit(".log", 1)[0]

        # Shift existing numbered logs: module_name.9.log -> module_name.10.log, etc.
        for i in range(max_logs - 1, 0, -1):
            old_file = f"{base_name}.{i}.log"
            new_file = f"{base_name}.{i + 1}.log"
            if os.path.exists(old_file):
                os.rename(old_file, new_file)

        # Move current log to module_name.1.log
        rotated_file = f"{base_name}.1.log"
        os.rename(log_file_path, rotated_file)

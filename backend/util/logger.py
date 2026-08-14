import logging
import math
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from backend.util.log_redaction import attach_redaction_filter, redact
from backend.util.version import get_version

# Size cap per log file. Set LOG_MAX_BYTES=0 to disable the cap.
DEFAULT_MAX_LOG_BYTES = 10 * 1024 * 1024


def create_bar(middle_text: str) -> str:
    """Build an 80-char separator bar with `middle_text` centered."""
    total_length = 80
    if len(middle_text) == 1:
        remaining_length = total_length - len(middle_text) - 2
        left_side_length = 0
        right_side_length = remaining_length
        return f"\n{middle_text * left_side_length}{middle_text}{middle_text * right_side_length}\n"

    remaining_length = total_length - len(middle_text) - 4
    left_side_length = math.floor(remaining_length / 2)
    right_side_length = remaining_length - left_side_length
    return f"\n{'*' * left_side_length} {middle_text} {'*' * right_side_length}\n"


def _max_log_bytes() -> int:
    # A negative value must NOT collapse to 0 — 0 is the documented "no cap"
    # opt-out, so that would silently restore unbounded growth.
    try:
        value = int(os.getenv("LOG_MAX_BYTES", "").strip() or DEFAULT_MAX_LOG_BYTES)
    except ValueError:
        return DEFAULT_MAX_LOG_BYTES
    return value if value >= 0 else DEFAULT_MAX_LOG_BYTES


def rotated_log_path(log_file_path: str, index: int) -> Optional[str]:
    """`<dir>/<name>.log` + N -> `<dir>/<name>.N.log`, or None if the FILENAME
    doesn't end in `.log`. Strip only the suffix — a `.log` inside a directory
    name would otherwise rewrite the path out of its own directory."""
    directory, sep, filename = log_file_path.rpartition(os.sep)
    if not filename.endswith(".log"):
        return None
    return f"{directory}{sep}{filename[: -len('.log')]}.{index}.log"


def rotation_namer(default_name: str) -> str:
    """Map RotatingFileHandler's `<base>.log.N` onto this app's `<base>.N.log`.
    prune_old_logs() and the log viewer both glob `*.log`, which the default
    naming would escape entirely."""
    base, _, index = default_name.rpartition(".")
    if not index.isdigit():
        return default_name
    return rotated_log_path(base, int(index)) or default_name


class SafeFormatter(logging.Formatter):
    """Formatter that sets the source tag and re-redacts the fully rendered line."""

    # SecretRedactionFilter is the primary layer; this catches records that never
    # passed a chub logger (a raw LogRecord formatted directly). Redaction is idempotent.

    def format(self, record):
        """Render the record, then re-redact the whole line."""
        source = getattr(record, "source", None)
        record.source_tag = f"[{source}]" if source else ""
        # Restore a buffered record's event time (see _BufferingLogger) so
        # replayed lines aren't all stamped with the flush time.
        orig_created = getattr(record, "orig_created", None)
        if orig_created is not None:
            record.created = orig_created
        return redact(super().format(record))


class Logger:
    """
    Enhanced logger with smart redaction, automatic log rotation, and cleaner initialization.
    """

    _initialized = set()

    @staticmethod
    def redact_sensitive_info(text: str) -> str:
        """Mask secret-shaped substrings in `text` (see backend.util.log_redaction)."""
        return redact(text)

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
        # Filter goes on the LOGGER, not each handler: it then runs once per
        # record and covers handlers attached later (root's ErrorNotifyHandler).
        attach_redaction_filter(self._logger)
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
        if os.path.isfile(log_file_path) and rotated_log_path(log_file_path, 1):
            # Shift existing numbered logs: module_name.9.log -> module_name.10.log, etc.
            for i in range(max_logs - 1, 0, -1):
                old_file = rotated_log_path(log_file_path, i)
                new_file = rotated_log_path(log_file_path, i + 1)
                if os.path.exists(old_file):
                    os.rename(old_file, new_file)

            os.rename(log_file_path, rotated_log_path(log_file_path, 1))

    def _setup_handlers(self, log_file_path: str, max_logs: int) -> None:
        """Setup logging handlers (redaction lives on the logger, not here)."""
        formatter = SafeFormatter(
            fmt="%(asctime)s %(levelname)s %(source_tag)s[%(filename)s]: %(message)s",
            datefmt="%d/%m/%Y %H:%M:%S",
        )

        # maxBytes must be non-zero or doRollover() never fires, and backupCount
        # must be >= 1 or rollover reopens the base file in append mode — the
        # size cap then bounds nothing and thrashes a rollover per record.
        # encoding is explicit: the redaction mask is non-ASCII, so the file must
        # not depend on the container locale to be writable.
        file_handler = RotatingFileHandler(
            log_file_path,
            mode="a",
            maxBytes=_max_log_bytes(),
            backupCount=max(1, max_logs),
            encoding="utf-8",
        )
        file_handler.namer = rotation_namer
        file_handler.setFormatter(formatter)
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
            # Marks the handler as tracking the logger's level, so a live
            # log_level change can be pushed onto it (api/utils.py).
            console.inherits_logger_level = not console_level
            console.addFilter(lambda record: record.levelno < logging.ERROR)
            console.setFormatter(SafeFormatter("%(message)s"))
            self._logger.addHandler(console)

        # Error console handler (always present for errors)
        error_console = logging.StreamHandler()
        error_console.setLevel(logging.ERROR)
        error_console.setFormatter(
            SafeFormatter(f"%(levelname)s [{self.module_name.upper()}]: %(message)s")
        )
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
    if os.path.isfile(log_file_path) and rotated_log_path(log_file_path, 1):
        # Shift existing numbered logs: module_name.9.log -> module_name.10.log, etc.
        for i in range(max_logs - 1, 0, -1):
            old_file = rotated_log_path(log_file_path, i)
            new_file = rotated_log_path(log_file_path, i + 1)
            if os.path.exists(old_file):
                os.rename(old_file, new_file)

        os.rename(log_file_path, rotated_log_path(log_file_path, 1))

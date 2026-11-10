"""Exception → a fixed phrase that is safe to send to the browser."""

import errno
import sqlite3
from typing import Tuple, Type

import pydantic
import requests

# Exception text quotes paths, hostnames and provider payloads (CodeQL
# py/stack-trace-exposure): only the type picks the phrase, so log the exception itself.
_REASONS: Tuple[Tuple[Type[BaseException], str], ...] = (
    # requests' errors subclass OSError, so they must come first.
    (requests.exceptions.Timeout, "timed out"),
    (requests.exceptions.ConnectionError, "could not connect"),
    (requests.exceptions.RequestException, "request failed"),
    # A ValidationError's text quotes the input, which can be a webhook URL.
    (pydantic.ValidationError, "invalid settings"),
    (sqlite3.OperationalError, "database busy or unavailable"),
    (sqlite3.Error, "database error"),
    (PermissionError, "permission denied"),
    (FileNotFoundError, "not found"),
    (FileExistsError, "already exists"),
    (IsADirectoryError, "is a folder"),
    (NotADirectoryError, "not a folder"),
    (TimeoutError, "timed out"),
    (ConnectionError, "could not connect"),
)
_OS_REASONS = {
    errno.EXDEV: "cross-device link",
    errno.ENOSPC: "disk full",
    errno.EROFS: "read-only file system",
}


def public_reason(exc: BaseException) -> str:
    """``permission denied``, ``timed out``: the kind of failure, never its text."""
    for kind, reason in _REASONS:
        if isinstance(exc, kind):
            return reason
    if isinstance(exc, OSError):
        return _OS_REASONS.get(exc.errno, "system error")
    return "unexpected error"


def failure_text(what: str, exc: BaseException) -> str:
    """``file op failed: permission denied — see the server log``."""
    return f"{what} failed: {public_reason(exc)} — see the server log"

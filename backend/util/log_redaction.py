"""Secret-shaped redaction for log output — the one owner of what a log line may carry.

Every chub logger gets `SecretRedactionFilter` attached once, so none of the
logger.* call sites redact by hand. Only token-shaped values are masked, and the
key stays visible: an operator must still be able to tell WHICH credential a
failing request used.
"""

import logging
import re
import traceback
from functools import lru_cache
from typing import Callable, FrozenSet, Iterable, Match, Optional, Pattern, Tuple, Union

MASK_SUFFIX = "…"
REDACTED = "[redacted]"
REDACTION_ERROR = "[redaction-error]"

# Below this length a 4-char prefix would reveal most of the secret.
MIN_PREFIXABLE_LEN = 12

# Header / query-string names that are never a config leaf key, so
# SENSITIVE_FIELD_NAMES (the config-side source of truth) doesn't carry them.
WIRE_SECRET_KEY_NAMES = frozenset(
    {"authorization", "password", "secret", "x-api-key", "x-plex-token"}
)

# `webhook` is a credential only when its value IS a URL — in prose ("Error
# persisting webhook: <message>") the next word is diagnostics, not a secret.
URL_VALUED_SECRET_KEY_NAMES = frozenset({"webhook"})

# Value run: stops at whitespace, quotes and separators. `[` is excluded so a
# second pass cannot re-match an already-masked `key=[redacted]`.
_VALUE = r"[^\s\"'&,;<>(){}\[\]]+"

# Newlines stay OUT of the separator: `\s*` would let a YAML key swallow the
# next line's key as its value, leaving that line's real secret unredacted.
_SEP = r"[\"']?[ \t]*[:=][ \t]*[\"']?"

# HTTP auth scheme word sitting between the key and the token it introduces.
_SCHEME = r"(?:(?:bearer|basic|digest|token)[ \t]+)?"

_Rule = Tuple[Pattern[str], Union[str, Callable[[Match[str]], str]]]


@lru_cache(maxsize=1)
def secret_key_names() -> FrozenSet[str]:
    """Every key name whose value is a secret: config's list plus wire-only names."""
    # Lazy: keeps the pydantic config tree off the `import logger` path.
    from backend.util.config import SENSITIVE_FIELD_NAMES

    names = {name.lower() for name in SENSITIVE_FIELD_NAMES} | WIRE_SECRET_KEY_NAMES
    return frozenset(names)


def _alternation(names: Iterable[str]) -> str:
    """Longest-first alternation, so a name never matches a prefix of a longer one."""
    return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))


def _mask(value: str) -> str:
    """Mask a secret value, keeping a 4-char prefix only when enough stays hidden."""
    if value.endswith(MASK_SUFFIX):
        return value  # already masked — a second pass must not eat the prefix
    if len(value) < MIN_PREFIXABLE_LEN:
        return REDACTED
    return f"{value[:4]}{MASK_SUFFIX}"


def _mask_match(match: Match[str]) -> str:
    """Rewrite a keyed match, keeping the `keep` group and masking the `secret` one."""
    return f"{match.group('keep')}{_mask(match.group('secret'))}"


@lru_cache(maxsize=1)
def _rules() -> Tuple[_Rule, ...]:
    """Compile the taxonomy once. Order matters: keyed rules before signatures."""
    # A bounded `foo_` / `x-` prefix matches spellings like `plex_token` without
    # listing every variant; the length cap keeps the scan linear.
    prefix = r"(?<![\w-])(?:[\w-]{0,40}[-_])?"
    opaque_names = secret_key_names() - URL_VALUED_SECRET_KEY_NAMES
    key = rf"{prefix}(?:{_alternation(opaque_names)})"
    url_key = rf"{prefix}(?:{_alternation(URL_VALUED_SECRET_KEY_NAMES)})"

    return (
        # (a1) URL userinfo — keep scheme and user, mask the password.
        (
            re.compile(
                r"(?P<keep>[a-z][a-z0-9+.\-]{0,15}://[^\s/:@]{1,256}:)"
                r"(?P<secret>[^\s/@]{1,256})(?=@)",
                re.IGNORECASE,
            ),
            _mask_match,
        ),
        # (a2) URL-valued keys — the credential is the path, so keep scheme and host.
        (
            re.compile(
                rf"(?P<keep>{url_key}{_SEP}[a-z][a-z0-9+.\-]{{0,15}}://"
                rf"[^\s/\"']{{1,256}}/)(?P<secret>{_VALUE})",
                re.IGNORECASE,
            ),
            _mask_match,
        ),
        # (b+c) Any known key name followed by its value — querystring, header,
        # JSON or YAML form. The optional auth scheme is part of `keep`: masking
        # "Bearer" instead of the token behind it would spare the secret.
        (
            re.compile(
                rf"(?P<keep>{key}{_SEP}{_SCHEME})(?P<secret>{_VALUE})",
                re.IGNORECASE,
            ),
            _mask_match,
        ),
        # (d) Self-identifying tokens — a signature, not a blanket hex/base64
        # match, so hashes and ids operators need stay readable.
        (
            re.compile(
                # A scheme word with no header key still introduces a token.
                r"(?P<keep>\bBearer[ \t]+)(?P<secret>[A-Za-z0-9._\-+/=]{16,})",
                re.IGNORECASE,
            ),
            _mask_match,
        ),
        (
            re.compile(r"https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]{60,}"),
            "https://discord.com/api/webhooks/[redacted]",
        ),
        (
            re.compile(r"\b\d{10,}-[a-zA-Z0-9]{20,}\.apps\.googleusercontent\.com\b"),
            "[redacted].apps.googleusercontent.com",
        ),
        (re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"), "GOCSPX-[redacted]"),
        (
            re.compile(
                r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
            ),
            "[redacted-jwt]",
        ),
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted-aws-key]"),
        (re.compile(r"\bgh[po]_[A-Za-z0-9]{30,}\b"), "[redacted-gh-token]"),
        (re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"), "[redacted-bcrypt]"),
        # Notifiarr's API key lives in the URL PATH, so no key name precedes it.
        (
            re.compile(
                r"(notifiarr\.com/api/v\d+/notification/passthrough/)"
                r"[A-Za-z0-9_\-]{8,}",
                re.IGNORECASE,
            ),
            r"\1[redacted]",
        ),
    )


def redact(text: str) -> str:
    """Mask secret-shaped substrings; on internal failure drop the line, never leak it."""
    if not isinstance(text, str) or not text:
        return text
    try:
        for pattern, replacement in _rules():
            text = pattern.sub(replacement, text)
        return text
    except Exception:
        return REDACTION_ERROR


def _format_exception(exc_info) -> str:
    """Render exc_info the way logging.Formatter would, so handlers reuse this text."""
    text = "".join(traceback.format_exception(*exc_info))
    return text[:-1] if text.endswith("\n") else text


class SecretRedactionFilter(logging.Filter):
    """Scrub secret-shaped substrings from a record before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact msg, args, exception text and stack info in place; never raise."""
        try:
            # Redact the RENDERED message: a secret split across msg and args by
            # lazy %-formatting is only visible once the two are joined.
            record.msg = redact(record.getMessage())
            record.args = ()
            if record.exc_info:
                # Caching the redacted text here means every formatter reuses it
                # instead of re-deriving the raw traceback.
                record.exc_text = redact(
                    record.exc_text or _format_exception(record.exc_info)
                )
            elif record.exc_text:
                record.exc_text = redact(record.exc_text)
            if record.stack_info:
                record.stack_info = redact(record.stack_info)
        except Exception:
            record.msg = REDACTION_ERROR
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def attach_redaction_filter(logger: Optional[logging.Logger]) -> None:
    """Attach the redaction filter to `logger` exactly once."""
    if logger is None or any(
        isinstance(existing, SecretRedactionFilter) for existing in logger.filters
    ):
        return
    logger.addFilter(SecretRedactionFilter())

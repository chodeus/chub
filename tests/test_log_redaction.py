"""Tests for the log redaction layer — what it masks, what it must leave alone,
and that a hostile record cannot take the logger down with it.

The URL-query cases carried over from test_logger_redaction.py: requests/rclone
exceptions surface the full URL, which is where tokens actually leak.
"""

import io
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from backend.util.log_redaction import (  # noqa: E402
    MASK_SUFFIX,
    REDACTED,
    REDACTION_ERROR,
    URL_VALUED_SECRET_KEY_NAMES,
    SecretRedactionFilter,
    redact,
    secret_key_names,
)
from backend.util.logger import Logger  # noqa: E402

PLEX_URL = "http://plex:32400/library/metadata/1?X-Plex-Token=abc123SECRETtoken"
PLEX_SECRET = "abc123SECRETtoken"
PLEX_MASKED = f"X-Plex-Token=abc1{MASK_SUFFIX}"


def _record(msg, args=()):
    """Build a LogRecord the way logger.<level>(msg, *args) would."""
    return logging.LogRecord("ut", logging.ERROR, __file__, 1, msg, args, None)


class _Exploding:
    """A message object that blows up where getMessage() renders it."""

    def __str__(self):
        """Raise instead of rendering."""
        raise RuntimeError("boom")


# ==== (a) URL credentials and query-string secrets ====


def test_plex_token_in_url_query_redacted():
    """The Plex token in a failing request URL is masked, key still visible."""
    out = redact(f"Failed to download database: 401 Client Error for url: {PLEX_URL}")
    assert PLEX_SECRET not in out
    assert PLEX_MASKED in out


def test_fanart_client_key_in_url_query_redacted():
    """fanart.tv client_key in an exception URL is masked."""
    out = redact(
        "fanart.tv request failed for logo: HTTPSConnectionPool host="
        "'webservice.fanart.tv' url: /v3/movies/123?client_key=0123456789abcdef0123456789abcdef"
    )
    assert "0123456789abcdef0123456789abcdef" not in out
    assert f"client_key=0123{MASK_SUFFIX}" in out


@pytest.mark.parametrize(
    "key", ["token", "apikey", "api_key", "client_secret", "password"]
)
def test_query_string_secret_keys_redacted(key):
    """Every documented query-string secret key masks its value only."""
    out = redact(f"http://host/x?{key}=SuperSecretValue1234&page=2")
    assert "SuperSecretValue1234" not in out
    assert f"{key}=Supe{MASK_SUFFIX}" in out
    assert "page=2" in out  # redaction stops at the next parameter


def test_url_userinfo_password_redacted():
    """A password in URL userinfo is masked; scheme, user and host stay readable."""
    out = redact("rclone: gdrive://alice:hunter2supersecret@drive.example.com/backups")
    assert "hunter2supersecret" not in out
    assert out.startswith("rclone: gdrive://alice:hunt")
    assert "@drive.example.com/backups" in out


# ==== (b) Header-shaped bearers ====


def test_authorization_bearer_header_redacted():
    """The token is masked, not the `Bearer` scheme word in front of it."""
    out = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdefghijklmnop")
    assert "eyJhbGciOiJIUzI1NiJ9abcdefghijklmnop" not in out
    assert out == f"Authorization: Bearer eyJh{MASK_SUFFIX}"


def test_header_dict_repr_redacted():
    """Both header shapes mask inside a printed headers dict."""
    out = redact(
        "headers={'Authorization': 'Bearer sk-live-1234567890abcdef', "
        "'X-Api-Key': 'deadbeefcafebabe0123'}"
    )
    assert "sk-live-1234567890abcdef" not in out
    assert "deadbeefcafebabe0123" not in out
    assert f"'Bearer sk-l{MASK_SUFFIX}'" in out
    assert f"'X-Api-Key': 'dead{MASK_SUFFIX}'" in out


def test_bare_bearer_token_redacted():
    """A bearer token with no header key in front of it still masks."""
    out = redact("retrying with Bearer abcdefghijklmnopqrstuvwxyz012345")
    assert "abcdefghijklmnopqrstuvwxyz012345" not in out
    assert f"Bearer abcd{MASK_SUFFIX}" in out


# ==== (c) Long opaque values behind a known key name ====


@pytest.mark.parametrize(
    "line",
    [
        '{"refresh_token": "1//0gLongRefreshTokenValue1234"}',
        "refresh_token: 1//0gLongRefreshTokenValue1234",
        "refresh_token=1//0gLongRefreshTokenValue1234",
        "  refresh_token = 1//0gLongRefreshTokenValue1234",
    ],
)
def test_key_value_forms_redacted(line):
    """JSON, YAML, querystring and spaced kv forms all mask the same value."""
    out = redact(line)
    assert "1//0gLongRefreshTokenValue1234" not in out
    assert f"1//0{MASK_SUFFIX}" in out


def test_yaml_block_redacts_every_line():
    """A dumped OAuth token block masks each value — no key eats the next line."""
    out = redact(
        "token:\n"
        "  access_token: ya29.a0AfB_verylongsecretvalue1234567890\n"
        "  refresh_token: 1//0gLongRefreshTokenValue1234567890abcd\n"
    )
    assert "ya29.a0AfB_verylongsecretvalue1234567890" not in out
    assert "1//0gLongRefreshTokenValue1234567890abcd" not in out
    assert f"access_token: ya29{MASK_SUFFIX}" in out
    assert f"refresh_token: 1//0{MASK_SUFFIX}" in out


def test_prefixed_key_variants_redacted():
    """A `plex_token` style spelling matches without listing every variant."""
    out = redact("plex_token=SuperSecretValue1234")
    assert "SuperSecretValue1234" not in out
    assert f"plex_token=Supe{MASK_SUFFIX}" in out


def test_every_sensitive_config_name_is_covered():
    """The key list tracks config's SENSITIVE_FIELD_NAMES — no second list to sync."""
    from backend.util.config import SENSITIVE_FIELD_NAMES

    assert {n.lower() for n in SENSITIVE_FIELD_NAMES} <= secret_key_names()
    for name in SENSITIVE_FIELD_NAMES:
        if name in URL_VALUED_SECRET_KEY_NAMES:
            continue  # value is a URL, covered by its own test below
        assert redact(f"{name}=SuperSecretValue1234") == f"{name}=Supe{MASK_SUFFIX}"


def test_webhook_url_masks_the_path_not_the_host():
    """A webhook URL is itself the credential, but the host is diagnostic."""
    out = redact("webhook: https://discord.com/api/webhooks/12345/" + "A" * 70)
    assert "A" * 70 not in out
    assert out == "webhook: https://discord.com/api/…"


def test_webhook_in_prose_is_left_alone():
    """`webhook:` in an error message is followed by diagnostics, not a secret."""
    msg = "Error persisting webhook: database is locked"
    assert redact(msg) == msg


# ==== Masking policy ====


def test_short_secret_never_leaks_a_prefix():
    """A short value is masked whole — 4 chars of it would be most of the secret."""
    assert redact("webhook_secret: abc") == f"webhook_secret: {REDACTED}"
    assert redact('{"webhook_secret": "abc"}') == f'{{"webhook_secret": "{REDACTED}"}}'


def test_empty_value_untouched():
    """An empty secret is nothing to hide — leave the line alone."""
    msg = '{"webhook_secret": ""}'
    assert redact(msg) == msg


def test_redaction_is_idempotent():
    """SafeFormatter re-runs redaction on the rendered line; the mask must survive."""
    once = redact(f"{PLEX_URL} Authorization: Bearer abcdefghijklmnopqrst")
    assert redact(once) == once
    assert PLEX_MASKED in once


# ==== Non-secrets stay readable ====


@pytest.mark.parametrize(
    "line",
    [
        "sha256 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 ok",
        "moved /mnt/user/data/media/Movies/Some Movie (2020)/poster.jpg",
        "tmdb id 550e8400-e29b-41d4-a716-446655440000 matched",
        "Fetched http://radarr:7878/api/v3/movie?page=2&sort=title fine",
        "run finished in 12.4s, 42 items, 3 skipped",
    ],
)
def test_non_secret_lines_untouched(line):
    """Hashes, paths, ids and plain URLs are the diagnostic payload — never mangled."""
    assert redact(line) == line


# ==== Filter mechanics ====


def test_filter_redacts_lazy_percent_args():
    """A secret passed as a %-arg is only visible once msg and args are joined."""
    record = _record("upload failed for %s", (PLEX_URL,))
    assert SecretRedactionFilter().filter(record) is True
    assert PLEX_SECRET not in record.getMessage()
    assert PLEX_MASKED in record.getMessage()


def test_filter_keeps_numeric_args_renderable():
    """Redacting must not stringify args — `%d` still has to format."""
    record = _record("scanned %d items in %.1fs", (42, 1.5))
    assert SecretRedactionFilter().filter(record) is True
    assert record.getMessage() == "scanned 42 items in 1.5s"


def test_filter_redacts_exc_info_traceback():
    """The traceback is where request URLs leak; the cached text must be masked."""
    try:
        raise ValueError(f"POST {PLEX_URL}")
    except ValueError:
        record = logging.LogRecord(
            "ut", logging.ERROR, __file__, 1, "upload failed", None, sys.exc_info()
        )
    assert SecretRedactionFilter().filter(record) is True
    assert PLEX_SECRET not in record.exc_text
    assert PLEX_MASKED in record.exc_text
    # A plain formatter reuses the cached text instead of re-deriving the raw one.
    assert PLEX_SECRET not in logging.Formatter("%(message)s").format(record)


def test_filter_redacts_stack_info():
    """stack_info is appended verbatim by the formatter, so it needs masking too."""
    record = _record("dumping stack")
    record.stack_info = f"Stack (most recent call last):\n  requesting {PLEX_URL}"
    assert SecretRedactionFilter().filter(record) is True
    assert PLEX_SECRET not in record.stack_info


def test_hostile_record_does_not_kill_logging():
    """A record whose getMessage() raises must not propagate out of the filter."""
    record = _record(_Exploding())
    assert SecretRedactionFilter().filter(record) is True
    assert record.msg == REDACTION_ERROR
    assert logging.Formatter("%(message)s").format(record) == REDACTION_ERROR


def test_hostile_record_drops_the_exception_text():
    """Failing closed means the traceback goes too — never emit it unredacted."""
    try:
        raise ValueError(f"POST {PLEX_URL}")
    except ValueError:
        record = logging.LogRecord(
            "ut", logging.ERROR, __file__, 1, _Exploding(), None, sys.exc_info()
        )
    assert SecretRedactionFilter().filter(record) is True
    assert PLEX_SECRET not in logging.Formatter("%(message)s").format(record)


def test_redact_fails_closed_not_open(monkeypatch):
    """If the engine itself breaks, drop the line — never fall back to the raw text."""

    def _boom():
        """Stand in for a redaction engine that blew up."""
        raise RuntimeError("engine down")

    monkeypatch.setattr("backend.util.log_redaction._rules", _boom)
    out = redact(f"upload failed for {PLEX_URL}")
    assert PLEX_SECRET not in out
    assert out == REDACTION_ERROR


# ==== Integration through the real chub Logger ====


def test_real_logger_redacts_through_a_plain_handler(tmp_path, monkeypatch):
    """A token-bearing URL logged through the real Logger lands masked in a handler
    with NO chub formatter — proof the record-level filter did the work."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.delenv("LOG_FILE", raising=False)
    name = "ut_log_redaction_e2e"
    log_file = tmp_path / name / f"{name}.log"
    module_logger = logging.getLogger(name)
    try:
        chub_logger = Logger(log_level="INFO", module_name=name)
        stream = io.StringIO()
        probe = logging.StreamHandler(stream)
        # Deliberately NOT SafeFormatter — only the filter can redact this one.
        probe.setFormatter(logging.Formatter("%(message)s"))
        module_logger.addHandler(probe)

        chub_logger._logger.error("poster upload failed for %s", PLEX_URL)
        for handler in module_logger.handlers:
            handler.flush()

        captured = stream.getvalue()
        assert PLEX_SECRET not in captured
        assert PLEX_MASKED in captured

        on_disk = log_file.read_text(encoding="utf-8")
        assert PLEX_SECRET not in on_disk
        assert PLEX_MASKED in on_disk
    finally:
        for handler in list(module_logger.handlers):
            handler.close()
            module_logger.removeHandler(handler)
        for existing in list(module_logger.filters):
            module_logger.removeFilter(existing)
        Logger._initialized.discard((name, str(log_file)))

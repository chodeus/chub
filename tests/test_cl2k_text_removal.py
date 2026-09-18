"""Tests for the LaMa sidecar's auth header and the key that feeds it.

The sidecar secret lives in its own ``client_key`` field so that switching
``ai_provider`` no longer overwrites whichever token was already in ``api_key``.
Configs written before the split are migrated once, at load — so ``_lama_headers``
has nothing to guess at, and an openai token parked in ``api_key`` is never
posted to the sidecar.
"""

import types

from backend.util.cl2k.config import Cl2kMakerConfig
from backend.util.cl2k.text_removal import _lama_headers
from backend.util.config import SENSITIVE_FIELD_NAMES, redact_secrets


def _cfg(**kw):
    return types.SimpleNamespace(**{"api_key": "", "client_key": "", **kw})


def test_client_key_is_sent_as_the_api_key_header():
    assert _lama_headers(_cfg(client_key="s3cret")) == {"X-API-Key": "s3cret"}


def test_keyless_sidecar_gets_no_header():
    assert _lama_headers(_cfg()) == {}


def test_pre_split_sidecar_secret_migrates_into_client_key():
    cfg = Cl2kMakerConfig(ai_provider="lama_sidecar", api_key="sidecar-secret")
    assert (cfg.client_key, cfg.api_key) == ("sidecar-secret", "")
    assert _lama_headers(cfg) == {"X-API-Key": "sidecar-secret"}


def test_an_openai_token_is_never_migrated_to_the_sidecar_key():
    """The live config had an openai token sitting in the shared field while the
    provider was already lama_sidecar. The sidecar has no use for it."""
    cfg = Cl2kMakerConfig(ai_provider="lama_sidecar", api_key="sk-proj-abc123")
    assert (cfg.client_key, cfg.api_key) == ("", "sk-proj-abc123")
    assert _lama_headers(cfg) == {}


def test_migration_never_clobbers_an_existing_client_key():
    cfg = Cl2kMakerConfig(
        ai_provider="lama_sidecar", api_key="legacy", client_key="current"
    )
    assert (cfg.client_key, cfg.api_key) == ("current", "legacy")


def test_openai_provider_config_is_left_alone():
    cfg = Cl2kMakerConfig(ai_provider="openai", api_key="sk-proj-abc")
    assert (cfg.client_key, cfg.api_key) == ("", "sk-proj-abc")


def test_client_key_is_redacted_on_the_config_api():
    """The field name is chosen to land in the core redaction list — renaming it
    to something more descriptive would leak the secret on GET /api/config."""
    assert "client_key" in SENSITIVE_FIELD_NAMES
    out = redact_secrets(
        {"cl2k_maker": {"client_key": "s3cret", "ai_endpoint": "http://x"}}
    )
    assert out["cl2k_maker"]["client_key"] == "********"
    assert out["cl2k_maker"]["ai_endpoint"] == "http://x"

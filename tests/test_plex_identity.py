"""Tests for backend.util.plex.apply_plex_identity — the pinned X-Plex-* headers
that stop each container rebuild registering a new device on the user's account."""

import plexapi
import plexapi.server
import pytest

import backend.util.plex as plex_mod
from backend.util.plex import PLEX_PRODUCT_NAME, apply_plex_identity


class _Log:
    def __init__(self):
        self.warnings = []

    def debug(self, *a, **k):
        pass

    def warning(self, msg, *a, **k):
        self.warnings.append(msg)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Reset the applied-once latch and the plexapi globals around each test."""
    monkeypatch.setattr(plex_mod, "_plex_identity_applied", False)
    monkeypatch.setattr(plexapi, "X_PLEX_IDENTIFIER", "0xdeadbeef")
    monkeypatch.setattr(plexapi, "X_PLEX_PRODUCT", "PlexAPI")
    monkeypatch.setattr(plexapi, "X_PLEX_DEVICE_NAME", "somehost")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    original = dict(plexapi.BASE_HEADERS)
    yield
    plexapi.BASE_HEADERS.clear()
    plexapi.BASE_HEADERS.update(original)


def test_headers_reach_the_dict_plexapi_server_holds():
    # plexapi/server.py does `from plexapi import BASE_HEADERS`, so the identity
    # must be applied by mutating that dict, not by rebinding the attribute.
    identifier = apply_plex_identity()

    assert plexapi.server.BASE_HEADERS is plexapi.BASE_HEADERS
    assert plexapi.server.BASE_HEADERS["X-Plex-Client-Identifier"] == identifier
    assert plexapi.server.BASE_HEADERS["X-Plex-Product"] == PLEX_PRODUCT_NAME
    assert plexapi.server.BASE_HEADERS["X-Plex-Device-Name"] == PLEX_PRODUCT_NAME


def test_identifier_is_persisted_and_reused(monkeypatch, tmp_path):
    first = apply_plex_identity()
    assert (tmp_path / "plex_client_id").read_text().strip() == first

    # A fresh process against the same CONFIG_DIR reads the stored id back.
    monkeypatch.setattr(plex_mod, "_plex_identity_applied", False)
    assert apply_plex_identity() == first


def test_is_idempotent_within_a_process(monkeypatch):
    first = apply_plex_identity()

    # The latch must short-circuit before minting a replacement.
    monkeypatch.setattr(
        plex_mod, "_stable_plex_identifier", lambda logger=None: "regenerated"
    )
    assert apply_plex_identity() == first


def test_unwritable_config_dir_falls_back_without_raising(monkeypatch):
    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr("builtins.open", boom)
    logger = _Log()

    identifier = apply_plex_identity(logger)

    assert identifier == plex_mod._PLEX_IDENTITY_FALLBACK
    assert plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] == identifier
    assert logger.warnings


def test_empty_identity_file_is_replaced(tmp_path):
    (tmp_path / "plex_client_id").write_text("   \n")

    identifier = apply_plex_identity()

    assert identifier.strip()
    assert identifier != plex_mod._PLEX_IDENTITY_FALLBACK
    assert (tmp_path / "plex_client_id").read_text().strip() == identifier

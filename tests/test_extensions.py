# tests/test_extensions.py
"""The extension discovery layer must be a clean no-op when no extension
packages are installed, and the registries it feeds must stay intact."""

from backend import extensions
from backend.modules import MODULES
from backend.util.config import ChubConfig
from backend.util.database.schema import SchemaManager


def test_aggregates_have_correct_empty_types():
    # On a branch with no extension subpackages every hook aggregates to empty.
    assert isinstance(extensions.extension_routers(), list)
    assert isinstance(extensions.extension_modules(), dict)
    assert isinstance(extensions.extension_config_fields(), dict)
    assert isinstance(extensions.extension_tables(), list)
    assert isinstance(extensions.extension_stream_prefixes(), tuple)


def test_core_module_registry_intact():
    # The MODULES.update(extension_modules()) hook must not disturb core entries.
    for key in ("poster_renamerr", "sync_gdrive", "border_replacerr"):
        assert key in MODULES


def test_config_builds_with_extension_fields_applied():
    # ChubConfig must instantiate after the create_model graft (or no-op).
    config = ChubConfig()
    assert config.general is not None


def test_schema_builds_with_extension_tables():
    manager = SchemaManager()
    assert "media_cache" in manager.tables


def test_stream_prefixes_collects_and_flattens(monkeypatch):
    # A manifest's stream_prefixes() is flattened into the aggregate tuple.
    class _FakeManifest:
        @staticmethod
        def stream_prefixes():
            return ("/api/ut-ext/",)

    monkeypatch.setattr(extensions, "_manifests", lambda: (_FakeManifest,))
    assert extensions.extension_stream_prefixes() == ("/api/ut-ext/",)

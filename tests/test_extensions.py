# tests/test_extensions.py
"""The extension discovery layer must be a clean no-op when no extension
packages are installed, and the registries it feeds must stay intact."""

import os
from types import SimpleNamespace

from backend import extensions
from backend.modules import MODULES
from backend.util.config import ChubConfig
from backend.util.database.schema import SchemaManager


def test_aggregates_have_correct_empty_types():
    # Whatever extensions exist, every hook aggregates to its container type.
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


class _GatedManifest(SimpleNamespace):
    """Stand-in with every hook, gated by a togglable available()."""


# An instance, not the class: type.__name__ is a data descriptor, so only an
# instance can carry the dotted module-style __name__ the loader parses.
_GATED = _GatedManifest(
    __name__="backend.extensions.ut_ext.manifest",
    ok=True,
    routers=lambda: ["router"],
    modules=lambda: {"ut_ext": object},
    config_fields=lambda: {"ut_ext": (dict, {})},
    tables=lambda: ["table"],
)
_GATED.available = lambda: _GATED.ok


def test_lean_flavor_disables_functional_hooks_but_not_data_hooks(monkeypatch):
    """CHUB_IMAGE_FLAVOR=lean: no routers/modules, config and tables intact."""
    monkeypatch.setattr(extensions, "_manifests", lambda: (_GATED,))
    monkeypatch.setattr(_GATED, "ok", True)
    monkeypatch.setenv("CHUB_IMAGE_FLAVOR", "lean")

    assert extensions.extension_routers() == []
    assert extensions.extension_modules() == {}
    assert extensions.enabled_extensions() == []
    assert "ut_ext" in extensions.extension_config_fields()  # data hooks survive
    assert extensions.extension_tables() == ["table"]


def test_unset_flavor_enables_everything(monkeypatch):
    """Dev boxes and CI carry no flavor var and behave like :full."""
    monkeypatch.setattr(extensions, "_manifests", lambda: (_GATED,))
    monkeypatch.setattr(_GATED, "ok", True)
    monkeypatch.delenv("CHUB_IMAGE_FLAVOR", raising=False)

    assert extensions.extension_routers() == ["router"]
    assert extensions.extension_modules() == {"ut_ext": object}
    assert extensions.enabled_extensions() == ["ut_ext"]


def test_manifest_available_false_gates_function_not_data(monkeypatch):
    """A dependency-missing extension keeps its config typed and tables built."""
    monkeypatch.setattr(extensions, "_manifests", lambda: (_GATED,))
    monkeypatch.setattr(_GATED, "ok", False)
    monkeypatch.delenv("CHUB_IMAGE_FLAVOR", raising=False)

    assert extensions.extension_routers() == []
    assert extensions.enabled_extensions() == []
    assert "ut_ext" in extensions.extension_config_fields()
    assert extensions.extension_tables() == ["table"]


def test_cl2k_available_on_a_dev_box_with_imagemagick():
    """This suite runs with wand importable, so the real gate reads True."""
    from backend.extensions.cl2k import manifest

    assert manifest.available() is True


def test_lean_boot_hides_extension_routes_but_keeps_config(tmp_path):
    """A lean-image process mounts no extension routes yet types cl2k config."""
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, '.');\n"
        "from backend.api.main import app\n"
        "from backend.util.config import ChubConfig\n"
        "paths, stack = [], list(app.routes)\n"
        "while stack:\n"
        "    r = stack.pop()\n"
        "    paths.append(getattr(r, 'path', ''))\n"
        "    stack.extend(getattr(r, 'routes', []) or [])\n"
        "    orig = getattr(r, 'original_router', None)\n"
        "    stack.extend(getattr(orig, 'routes', []) or [])\n"
        "assert any('/api/posters' in p for p in paths), 'walk broken'\n"
        "hits = [p for p in paths if 'cl2k' in p or 'self-heal' in p]\n"
        "assert not hits, hits\n"
        "assert hasattr(ChubConfig(), 'cl2k_maker')\n"
        "assert hasattr(ChubConfig(), 'poster_self_heal')\n"
        "print('LEAN-OK')\n"
    )
    env = dict(
        os.environ,
        CHUB_IMAGE_FLAVOR="lean",
        CONFIG_DIR=str(tmp_path),
        LOG_DIR=str(tmp_path / "logs"),
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "LEAN-OK" in proc.stdout

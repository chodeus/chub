"""The Logs API must accept config-only extension modules (e.g. cl2k_maker on
develop) that log via get_module_logger but aren't in the runnable MODULES
registry — otherwise their log file exists but the Logs page can't list/open it.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backend.api.logs as logs  # noqa: E402


def test_valid_log_modules_includes_extension_config_modules(monkeypatch):
    monkeypatch.setattr(
        logs, "extension_config_fields", lambda: {"ut_ext_logmod": (object, None)}
    )
    valid = logs._valid_log_modules()
    assert "ut_ext_logmod" in valid  # config-only extension module is serveable
    assert "general" in valid


def test_valid_log_modules_without_extensions_is_modules_plus_general(monkeypatch):
    from backend.modules import MODULES

    monkeypatch.setattr(logs, "extension_config_fields", lambda: {})
    assert logs._valid_log_modules() == set(MODULES.keys()) | {"general"}

"""Regression: a module Logger must attach its OWN file handler even when the
root logger already has one.

Once the failure-notification ErrorNotifyHandler is installed on the root logger,
`logging.Logger.hasHandlers()` returns True for every module logger (it walks up
to root). The old setup used hasHandlers() to decide whether to attach the
per-module file handler, so a module first logged at run time (extensions like
poster_self_heal) silently skipped its file handler and its run logs never
reached <module>.log. The fix checks the logger's OWN handlers instead.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.logger import Logger  # noqa: E402


def test_module_logger_attaches_file_handler_despite_root_handler(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    name = "ut_modlog_regression"
    log_file = tmp_path / name / f"{name}.log"

    root = logging.getLogger()
    sentinel = logging.NullHandler()  # stand-in for the ErrorNotifyHandler on root
    root.addHandler(sentinel)
    try:
        lg = Logger(log_level="INFO", module_name=name)
        # Must have its OWN handler — not rely on the root logger's.
        assert lg._logger.handlers, "module logger got no own file handler"

        lg._logger.info("hello-from-regression-test")
        for h in lg._logger.handlers:
            h.flush()

        assert log_file.exists(), "module log file was never created"
        assert "hello-from-regression-test" in log_file.read_text()
    finally:
        root.removeHandler(sentinel)
        mod_logger = logging.getLogger(name)
        for h in list(mod_logger.handlers):
            h.close()
            mod_logger.removeHandler(h)
        Logger._initialized.discard((name, str(log_file)))

# util/base_module.py

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from backend.util.config import load_config
from backend.util.logger import Logger


class ChubModule(ABC):
    def __init__(
        self, config: Optional[Dict[str, Any]] = None, logger: Optional[Logger] = None
    ) -> None:
        """
        Initialize module with optional logger injection.

        Args:
            logger: Optional logger instance for server mode.
                   If None, creates module-specific logger for CLI mode.
        """
        self._cancel_event: Optional[threading.Event] = None
        self.full_config = load_config()

        try:
            module_name = self._get_module_name()
        except Exception as e:
            raise ValueError(f"Failed to determine module name: {e}")

        self.config = getattr(self.full_config, module_name, None)

        if self.config is None:
            raise ValueError(f"No configuration found for module: {module_name}")

        if logger is not None:
            self.logger = logger.get_adapter(module_name.upper())
        else:
            log_level = getattr(self.config, "log_level", "INFO")
            self.logger = Logger(
                log_level=log_level,
                module_name=module_name,
                max_logs=self.full_config.general.max_logs,
            )

    def _get_module_name(self) -> str:
        """
        Return this module's registry key from modules.MODULES.

        Raises:
            LookupError: if this class is not registered in the MODULES mapping.
            TypeError: if the MODULES registry is not a dict-like mapping.
        """
        from backend.modules import MODULES

        # Validate registry is dict-like
        try:
            items = MODULES.items()
        except Exception as e:
            raise TypeError(f"Invalid MODULES registry: {e}")

        for module_name, module_class in items:
            # Exact class match only to avoid ambiguity
            if module_class is self.__class__ or module_class == self.__class__:
                return module_name

        # Nothing matched: make the error explicit and actionable
        raise LookupError(
            f"{self.__class__.__name__} is not registered in modules.MODULES; "
            "add it to modules/__init__.py: MODULES['<key>'] = <Class>"
        )

    def set_cancel_event(self, event: threading.Event) -> None:
        """Attach a cancel event so the module can be stopped cooperatively."""
        self._cancel_event = event

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested. Modules should call this
        periodically in long-running loops and exit early when True."""
        return self._cancel_event is not None and self._cancel_event.is_set()

    def set_job_context(self, job_id: Optional[int], db: Any) -> None:
        """Attach a job ID and shared db context so the module can report
        progress to the jobs queue mid-run.

        Job processor wires this in before calling .run(). Modules that
        want progress visibility on the Jobs page call _report_progress()
        at sensible checkpoints; modules that don't can ignore both.
        """
        self._job_id = job_id
        self._job_db = db

    def _report_progress(self, percent: int) -> None:
        """Update job progress on the Jobs page (clamped to 0..100).

        No-op if set_job_context() wasn't called or supplied a None job_id —
        modules call this freely without guarding for the unbound case
        (e.g. CLI runs, ad-hoc invocations).
        """
        job_id = getattr(self, "_job_id", None)
        db = getattr(self, "_job_db", None)
        if not job_id or db is None:
            return
        try:
            pct = max(0, min(100, int(percent)))
            db.worker.update_progress("jobs", job_id, pct)
        except Exception:  # noqa: S110 — progress is non-critical
            pass

    @abstractmethod
    def run(self) -> None:
        pass

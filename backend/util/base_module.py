# util/base_module.py

import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
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

        Wire this in when a module has a multi-minute phase that would
        otherwise leave the Jobs page stuck at 0% (or stuck at whatever
        previous-phase ceiling was reported). See poster_renamerr.py for
        the ladder pattern: define class-level _XYZ_PROGRESS_CEILING_PCT
        constants per phase, allocate the 0..100 range proportionally to
        expected wall-clock duration, and update every N iterations
        (every 250-2500 depending on iteration rate) plus a final pin at
        the ceiling on phase completion. Don't bother for fast modules
        where the job already snaps from 0 to 100 in seconds.
        """
        job_id = getattr(self, "_job_id", None)
        db = getattr(self, "_job_db", None)
        if not job_id or db is None:
            return
        try:
            pct = max(0, min(100, int(percent)))
            # Map the module's 0..100 into its progress window (default 0..100,
            # i.e. identity). A non-identity window lets a module that runs
            # another inline have the child advance a reserved slice of the
            # parent's bar — see set_progress_window().
            floor = getattr(self, "_progress_floor", 0)
            ceiling = getattr(self, "_progress_ceiling", 100)
            mapped = floor + (ceiling - floor) * pct / 100
            mapped = max(0, min(100, int(round(mapped))))
            db.worker.update_progress("jobs", job_id, mapped)
        except Exception:  # noqa: S110 — progress is non-critical
            pass

    def set_progress_window(self, floor: int, ceiling: int) -> None:
        """Map this module's 0..100 progress reports into [floor, ceiling] of
        the parent job's bar (default is the full 0..100 — identity).

        Used when an orchestrating module runs another inline and wants the
        child's progress to advance only a reserved tail of the bar, so the
        percentage keeps moving during a long final phase instead of pinning
        100 early. See poster_renamerr -> asset_renamerr.
        """
        self._progress_floor = max(0, min(100, int(floor)))
        self._progress_ceiling = max(self._progress_floor, min(100, int(ceiling)))

    def _declare_phases(self, names) -> None:
        """Seed the ordered list of pipeline phases this run will execute so the
        Jobs page shows what's coming. No-op without job context (CLI / nested
        sub-module calls). See _phase()."""
        job_id = getattr(self, "_job_id", None)
        db = getattr(self, "_job_db", None)
        if not job_id or db is None:
            return
        try:
            db.worker.declare_phases("jobs", job_id, list(names))
        except Exception:  # noqa: S110 — phase tracking is non-critical
            pass

    @contextmanager
    def _phase(self, name: str):
        """Record one sub-step's timing on the job (start → success/error).

        Wrap an orchestrated sub-phase: ``with self._phase("sync_gdrive"): ...``.
        No-op when there's no job context, so nested context-less sub-module
        instances don't double-record — the parent owns the phase. Phase
        bookkeeping never masks a real error: the work's exception propagates
        after the phase is marked ``error``.
        """
        job_id = getattr(self, "_job_id", None)
        db = getattr(self, "_job_db", None)
        if not job_id or db is None:
            yield
            return
        try:
            db.worker.start_phase("jobs", job_id, name)
        except Exception:  # noqa: S110 — phase tracking is non-critical
            pass
        try:
            yield
        except Exception as e:
            try:
                db.worker.finish_phase("jobs", job_id, name, status="error", error=e)
            except Exception:  # noqa: S110
                pass
            raise
        else:
            try:
                db.worker.finish_phase("jobs", job_id, name, status="success")
            except Exception:  # noqa: S110
                pass

    def _finalize_phases(self) -> None:
        """Mark any declared-but-unreached phases ``skipped``. Call once at the
        end of a run (in a finally). No-op without job context."""
        job_id = getattr(self, "_job_id", None)
        db = getattr(self, "_job_db", None)
        if not job_id or db is None:
            return
        try:
            db.worker.skip_pending_phases("jobs", job_id)
        except Exception:  # noqa: S110 — phase tracking is non-critical
            pass

    @abstractmethod
    def run(self) -> None:
        pass

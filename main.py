#!/usr/bin/env python3

import argparse
import atexit
import os
import signal
import sys
import threading
import time
from typing import Any, List, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from backend.util.config import ChubConfig, get_config_path, load_config
from backend.util.logger import Logger
from backend.util.module_orchestrator import ModuleOrchestrator
from backend.util.scheduler import ChubScheduler
from backend.util.version import get_version

SHUTDOWN_POLL_SECONDS = 60.0  # Interval for main thread to poll for shutdown


class ConfigFileHandler(FileSystemEventHandler):
    """Watch config.yml for changes and trigger reload with debounce."""

    def __init__(self, callback, debounce_interval=1):
        super().__init__()
        self.callback = callback
        self.last_modified = 0
        self.debounce_interval = debounce_interval

    def on_modified(self, event):
        if event.src_path.endswith("config.yml"):
            now = time.time()
            if now - self.last_modified > self.debounce_interval:
                self.last_modified = now
                self.callback()


class ChubApplication:
    """Main application class - handles lifecycle, infrastructure, and coordination"""

    def __init__(self):
        self.module_orchestrator: Optional[ModuleOrchestrator] = None
        self.scheduler: Optional[ChubScheduler] = None
        self.logger: Optional[Logger] = None
        self.config: Optional[ChubConfig] = None
        self.observer: Optional[Observer] = None
        self.shutdown_requested = threading.Event()
        self.cleanup_done = False
        self._cleanup_lock = threading.Lock()
        self._cleanup_started = threading.Event()

    def setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown"""
        import os

        def hard_exit(signum: int, frame: Any) -> None:
            if self.logger:
                self.logger.get_adapter("MAIN").warning(
                    f"Received second signal {signum}, force exiting immediately"
                )
            else:
                print(
                    f"[MAIN] Received second signal {signum}, force exiting immediately"
                )
            os._exit(1)

        def first_signal(signum: int, frame: Any) -> None:
            if self.logger:
                self.logger.get_adapter("MAIN").info(
                    f"Received signal {signum}, initiating shutdown..."
                )
            else:
                print(f"[MAIN] Received signal {signum}, initiating shutdown...")

            # Tell the rest of the app to stop
            self.shutdown_requested.set()

            # Launch cleanup exactly once
            if not self._cleanup_started.is_set():
                self._cleanup_started.set()
                threading.Thread(target=self.cleanup, daemon=True).start()

            # After the first signal, escalate subsequent signals to immediate exit
            signal.signal(signal.SIGINT, hard_exit)
            signal.signal(signal.SIGTERM, hard_exit)

        signal.signal(signal.SIGINT, first_signal)
        signal.signal(signal.SIGTERM, first_signal)
        atexit.register(self.cleanup)

    def cleanup(self) -> None:
        """Clean up resources (idempotent, thread-safe)"""
        if self.cleanup_done:
            return
        with self._cleanup_lock:
            if self.cleanup_done:
                return
            try:
                if self.logger:
                    log = self.logger.get_adapter("MAIN")
                    log.info("Cleaning up application resources...")
                else:
                    print("[MAIN] Cleaning up application resources...")

                if self.observer:
                    self.observer.stop()

                if self.scheduler:
                    self.scheduler.stop()

                # No need to clean up ModuleOrchestrator - jobs are handled by worker

                self.cleanup_done = True

                if self.logger:
                    self.logger.get_adapter("MAIN").info("Cleanup completed")
                else:
                    print("[MAIN] Cleanup completed")

            except Exception as e:
                if self.logger:
                    self.logger.get_adapter("MAIN").error(f"Error during cleanup: {e}")
                else:
                    print(f"[MAIN] Error during cleanup: {e}")
                self.cleanup_done = True

    def run(self, args: argparse.Namespace) -> int:
        """Main application run method"""
        try:
            try:
                self.config = load_config()
            except Exception as e:
                print(f"[CHUB] ERROR loading config: {e}", file=sys.stderr)
                return 1

            if args.modules:
                import os

                os.environ["LOG_TO_CONSOLE"] = "true"
                log_level = getattr(self.config.general, "log_level", "INFO")
                self.logger = Logger(
                    log_level=log_level,
                    module_name="general",
                    max_logs=self.config.general.max_logs,
                )
            else:
                import os

                os.environ["LOG_TO_CONSOLE"] = "false"
                log_level = getattr(self.config.general, "log_level", "INFO")
                self.logger = Logger(
                    log_level=log_level,
                    module_name="general",
                    max_logs=self.config.general.max_logs,
                )

            self.module_orchestrator = ModuleOrchestrator(logger=self.logger)

            if args.modules:
                return self.run_cli_modules(args.modules)
            else:
                return self.run_server_mode()

        except KeyboardInterrupt:
            if self.logger:
                self.logger.get_adapter("MAIN").info("Keyboard interrupt received")
            else:
                print("[MAIN] Keyboard interrupt received")
            return 0
        except Exception as e:
            if self.logger:
                self.logger.get_adapter("MAIN").error(
                    f"FATAL exception: {e}", exc_info=True
                )
            else:
                print(f"[MAIN] FATAL exception: {e}", file=sys.stderr)
            return 1

    def run_cli_modules(self, modules: List[str]) -> int:
        """Run CLI modules - simple execution without job queue overhead"""
        try:
            if self.logger:
                self.logger.get_adapter("MAIN").info(
                    f"CLI mode: Running modules {modules}"
                )

            # Use simple orchestrator for CLI (bypasses job queue for simplicity)
            self.module_orchestrator.run_module_cli(modules)
            return 0
        except Exception as e:
            if self.logger:
                self.logger.get_adapter("MAIN").error(f"CLI error: {e}", exc_info=True)
            else:
                print(f"[MAIN] CLI error: {e}", file=sys.stderr)
            return 1

    def run_server_mode(self) -> int:
        """Run server mode with full infrastructure"""
        if self.logger:
            self.logger.get_adapter("MAIN").info("Starting CHUB server...")
        else:
            print("[MAIN] Starting CHUB server...")

        try:
            self.scheduler = ChubScheduler(
                config=self.config,
                logger=self.logger,
                module_orchestrator=self.module_orchestrator,
            )

            self.start_web_server()

            self._start_config_watcher()

            self.setup_signal_handlers()

            self.run_scheduler_loop()

            if self.logger:
                self.logger.get_adapter("MAIN").info("Exiting application")
            else:
                print("[MAIN] Exiting application")

            return 0

        except Exception as e:
            if self.logger:
                self.logger.get_adapter("MAIN").error(
                    f"Server error: {e}", exc_info=True
                )
            else:
                print(f"[MAIN] Server error: {e}", file=sys.stderr)
            return 1

    def start_web_server(self) -> None:
        try:
            from backend.api.server import start_web_server

            start_web_server(
                logger=self.logger, module_orchestrator=self.module_orchestrator
            )
            if self.logger:
                self.logger.get_adapter("MAIN").info(
                    "Web server started in background thread."
                )
        except Exception as e:
            if self.logger:
                self.logger.get_adapter("MAIN").error(
                    f"Failed to start web server: {e}", exc_info=True
                )
            else:
                print(f"[MAIN] Failed to start web server: {e}")
            raise

    def _start_config_watcher(self) -> None:
        """Start watching config.yml for changes and auto-reload."""
        try:
            config_path = get_config_path()
            config_dir = os.path.dirname(config_path)
            if not os.path.isdir(config_dir):
                os.makedirs(config_dir, exist_ok=True)

            handler = ConfigFileHandler(self._on_config_changed)
            self.observer = Observer()
            self.observer.daemon = True
            self.observer.schedule(handler, path=config_dir, recursive=False)
            self.observer.start()

            if self.logger:
                self.logger.get_adapter("MAIN").info(
                    f"Config watcher started on {config_dir}"
                )
        except Exception as e:
            if self.logger:
                self.logger.get_adapter("MAIN").warning(
                    f"Failed to start config watcher: {e}"
                )

    def _on_config_changed(self) -> None:
        """Reload config on file change. Keeps old config if validation fails."""
        log = self.logger.get_adapter("MAIN") if self.logger else None
        try:
            new_config = load_config()
            self.config = new_config
            if self.scheduler:
                self.scheduler.config = new_config
            if log:
                log.info("Configuration reloaded successfully")
        except SystemExit:
            # load_config calls sys.exit on validation errors - catch and keep old config
            if log:
                log.warning(
                    "Config reload failed (validation error). Keeping previous config."
                )
        except Exception as e:
            if log:
                log.warning(f"Config reload failed: {e}. Keeping previous config.")

    def run_scheduler_loop(self) -> None:
        """Run the scheduler loop with proper shutdown handling"""
        try:
            # Start scheduler
            self.scheduler.start()

            # Main thread waits for shutdown
            while not self.shutdown_requested.is_set():
                if self.shutdown_requested.wait(timeout=SHUTDOWN_POLL_SECONDS):
                    break

        except Exception as e:
            if self.logger:
                self.logger.get_adapter("MAIN").error(
                    f"FATAL error in scheduler loop: {e}", exc_info=True
                )
            else:
                print(f"[MAIN] FATAL error: {e}", file=sys.stderr)
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CHUB modules, schedule, or web UI."
    )
    parser.add_argument(
        "modules", nargs="*", help="Module names to run once (CLI mode)."
    )
    parser.add_argument("--version", action="version", version=get_version())
    parser.add_argument(
        "--reset-auth",
        action="store_true",
        help="Reset authentication credentials. Clears username, password, and JWT secret so you can re-run first-time setup.",
    )
    return parser.parse_args()


def reset_auth() -> int:
    """Clear auth credentials and regenerate JWT secret, then exit."""
    from backend.util.config import save_config

    try:
        config = load_config()
    except Exception as e:
        print(f"[CHUB] ERROR loading config: {e}", file=sys.stderr)
        return 1

    config.auth.username = ""
    config.auth.password_hash = ""
    config.auth.jwt_secret = ""
    save_config(config)

    print("[CHUB] Authentication has been reset.")
    print("[CHUB] Restart the container and visit the web UI to create a new admin account.")
    return 0


def main() -> None:
    args = parse_args()

    if args.reset_auth:
        sys.exit(reset_auth())

    app = ChubApplication()
    exit_code = app.run(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

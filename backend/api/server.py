# api/server.py
"""
Web server startup with proper dependency injection.
"""

import os
import threading
import time
from typing import TYPE_CHECKING

import uvicorn

# Readiness deadline, matched to the container health-check start period in
# deploy/docker/Dockerfile; exceeding it fails the boot.
STARTUP_TIMEOUT_SECONDS = 45

if TYPE_CHECKING:
    from backend.util.logger import Logger
    from backend.util.module_orchestrator import ModuleOrchestrator


def start_web_server(
    logger: "Logger", module_orchestrator: "ModuleOrchestrator"
) -> None:
    """
    Start web server with proper dependency injection.

    Args:
        logger: Logger instance
        module_orchestrator: ModuleOrchestrator instance for handling module execution
    """

    startup_error: list = []
    server_holder: list = []

    def run_server() -> None:
        try:
            from backend.api.main import app

            # Inject dependencies into app state
            app.state.logger = logger
            app.state.module_orchestrator = module_orchestrator

            port = int(os.environ.get("PORT") or "8000")
            host = os.environ.get("HOST") or "0.0.0.0"

            logger.get_adapter("SERVER").info(f"Starting web server on {host}:{port}")

            # Server, not uvicorn.run: `started` is the readiness signal the
            # caller waits on, so a bind failure is not a silent no-UI boot.
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host=host,
                    port=port,
                    log_config=None,  # Disable uvicorn logging
                    access_log=False,  # Disable access logging
                )
            )
            server_holder.append(server)
            server.run()
        except (Exception, SystemExit) as e:
            # uvicorn raises SystemExit(3) on a bind failure, and SystemExit is
            # a BaseException — `except Exception` would let it vanish here.
            logger.get_adapter("SERVER").error(f"Web server error: {e}", exc_info=True)
            startup_error.append(e)

    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for a real verdict: a bind failure kills only this thread, leaving a
    # container that is up, scheduling, and serving nothing.
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server_holder and server_holder[0].started:
            return
        if startup_error or not server_thread.is_alive():
            break
        time.sleep(0.05)

    if startup_error:
        raise RuntimeError("Web server failed to start") from startup_error[0]
    if not server_thread.is_alive():
        raise RuntimeError("Web server thread exited before it began listening")
    if server_holder:
        server_holder[0].should_exit = True
    raise RuntimeError(
        f"Web server did not begin listening within {STARTUP_TIMEOUT_SECONDS}s"
    )

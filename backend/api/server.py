# api/server.py
"""
Web server startup with proper dependency injection.
"""

import os
import threading
from typing import TYPE_CHECKING

import uvicorn

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

    def run_server() -> None:
        try:
            from backend.api.main import app

            # Inject dependencies into app state
            app.state.logger = logger
            app.state.module_orchestrator = module_orchestrator

            port = int(os.environ.get("PORT") or "8000")
            host = os.environ.get("HOST") or "0.0.0.0"

            logger.get_adapter("SERVER").info(f"Starting web server on {host}:{port}")

            uvicorn.run(
                app,
                host=host,
                port=port,
                log_config=None,  # Disable uvicorn logging
                access_log=False,  # Disable access logging
            )
        except Exception as e:
            logger.get_adapter("SERVER").error(f"Web server error: {e}", exc_info=True)
            raise

    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

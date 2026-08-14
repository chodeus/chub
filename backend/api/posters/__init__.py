"""
Poster management API endpoints for CHUB.

Provides poster operations including statistics, file management,
upload operations, and directory analysis functionality.
"""

from backend.api.posters._shared import get_cleanarr_logger, router

# Import order below IS route-registration order, which is FastAPI's matching
# order — do not sort. `items` must stay last or /{poster_id} shadows the rest.
from backend.api.posters import catalog  # noqa: F401
from backend.api.posters import browse  # noqa: F401
from backend.api.posters import collections  # noqa: F401
from backend.api.posters import storage  # noqa: F401
from backend.api.posters import matching  # noqa: F401
from backend.api.posters import gdrive  # noqa: F401
from backend.api.posters import files  # noqa: F401
from backend.api.posters import reports  # noqa: F401
from backend.api.posters import plex_metadata  # noqa: F401
from backend.api.posters import items  # noqa: F401

__all__ = ["get_cleanarr_logger", "router"]

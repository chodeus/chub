# modules/__init__.py

from .asset_renamerr import AssetRenamerr
from .border_replacerr import BorderReplacerr
from .health_checkarr import HealthCheckarr
from .jduparr import Jduparr
from .labelarr import Labelarr
from .nestarr import Nestarr
from .nohl import Nohl
from .plex_maintenance import PlexMaintenance
from .poster_cleanarr import PosterCleanarr
from .poster_renamerr import PosterRenamerr
from .renameinatorr import Renameinatorr
from .sync_gdrive import SyncGDrive
from .unmatched_assets import UnmatchedAssets
from .upgradinatorr import Upgradinatorr

MODULES = {
    "sync_gdrive": SyncGDrive,
    "poster_renamerr": PosterRenamerr,
    "asset_renamerr": AssetRenamerr,
    "border_replacerr": BorderReplacerr,
    "upgradinatorr": Upgradinatorr,
    "renameinatorr": Renameinatorr,
    "nohl": Nohl,
    "labelarr": Labelarr,
    "health_checkarr": HealthCheckarr,
    "jduparr": Jduparr,
    "nestarr": Nestarr,
    "poster_cleanarr": PosterCleanarr,
    "plex_maintenance": PlexMaintenance,
    "unmatched_assets": UnmatchedAssets,
}

# Self-registering extension modules (none on main; see backend/extensions).
# Imported last so an extension's own imports of backend.modules.* resolve
# against the already-populated package.
from backend.extensions import extension_modules  # noqa: E402

MODULES.update(extension_modules())

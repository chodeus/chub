# modules/__init__.py

from .border_replacerr import BorderReplacerr
from .health_checkarr import HealthCheckarr
from .jduparr import Jduparr
from .labelarr import Labelarr
from .nestarr import Nestarr
from .nohl import Nohl
from .poster_cleanarr import PosterCleanarr
from .poster_renamerr import PosterRenamerr
from .renameinatorr import Renameinatorr
from .sync_gdrive import SyncGDrive
from .unmatched_assets import UnmatchedAssets
from .upgradinatorr import Upgradinatorr

MODULES = {
    "sync_gdrive": SyncGDrive,
    "poster_renamerr": PosterRenamerr,
    "border_replacerr": BorderReplacerr,
    "upgradinatorr": Upgradinatorr,
    "renameinatorr": Renameinatorr,
    "nohl": Nohl,
    "labelarr": Labelarr,
    "health_checkarr": HealthCheckarr,
    "jduparr": Jduparr,
    "nestarr": Nestarr,
    "poster_cleanarr": PosterCleanarr,
    "unmatched_assets": UnmatchedAssets,
}

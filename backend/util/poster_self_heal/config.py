# backend/util/poster_self_heal/config.py
"""Pydantic config model for the poster_self_heal extension.

Grafted onto ChubConfig by backend/extensions/poster_self_heal/manifest.py
(config_fields), so ``load_config().poster_self_heal`` is typed like the core
module sections. Lives here (not backend/util/config.py) because poster_self_heal
is a develop-only extension.

Deliberately has NO source/drive fields: the healer operates on the CL2K maker's
output, reading ``cl2k_maker.output_dir`` + ``cl2k_maker.gdrive_folder_id`` (and
``cl2k_maker.style``) from the loaded config at run time.
"""

from pydantic import BaseModel


class PosterSelfHealConfig(BaseModel):
    log_level: str = "info"

    # Which kinds of drift to detect and propose. (Per-id TMDB lookups are cached
    # by the TMDB client's own cache_expiration, so a scheduled run re-checks every
    # poster cheaply without a separate recheck interval here.)
    heal_ids: bool = True  # stale/merged embedded TMDB id no longer resolves
    heal_titles: bool = True  # the title on TMDB changed since the poster was named
    backfill_ids: bool = True  # add a resolved {tmdb-id} to an id-less poster

# backend/util/poster_self_heal/config.py
"""Pydantic config model for the poster_self_heal extension.

Grafted onto ChubConfig by backend/extensions/poster_self_heal/manifest.py
(config_fields), so ``load_config().poster_self_heal`` is typed like the core
module sections. Lives here (not backend/util/config.py) because poster_self_heal
is part of the :full image.

Deliberately has NO source/drive fields: the healer operates on the CL2K maker's
output, reading ``cl2k_maker.local_folders`` + ``cl2k_maker.gdrive_uploads`` (and
``cl2k_maker.style``) from the loaded config at run time.
"""

from pydantic import BaseModel


class PosterSelfHealConfig(BaseModel):
    log_level: str = "info"

    # The healer rebuilds each poster's canonical DAPS filename from its live
    # library row (current tmdb/tvdb/imdb ids) + TMDB's canonical title/year, and
    # proposes the rename when it differs — so id, title, and year drift are all
    # healed together (a filename is canonical or it isn't; partial heals don't
    # make sense). Per-id TMDB lookups are cached by the TMDB client's own
    # cache_expiration, so a scheduled run re-checks every poster cheaply.
    #
    # The one genuinely-optional behaviour: whether to also ADD ids to a poster
    # that has none (backfill), vs only correcting posters that already carry one.
    backfill_ids: bool = True

    # When True, confident proposals are applied automatically during the run
    # (renamed on Drive + locally) instead of waiting for manual review. Ambiguous
    # matches (multiple library items share a title) ALWAYS go to the review queue
    # regardless — they have no single safe rename to auto-apply.
    auto_apply: bool = False

# backend/extensions/poster_self_heal/manifest.py
"""Self-registration manifest for the poster_self_heal extension.

Discovered by backend/extensions/__init__.py. Every hook imports its payload
lazily — manifests are imported while core modules (config, schema) are still
initialising, so module-level imports here would risk circular imports.
"""


def routers():
    from backend.api.poster_self_heal import router

    return [router]


def modules():
    from backend.modules.poster_self_heal import PosterSelfHeal

    return {"poster_self_heal": PosterSelfHeal}


def config_fields():
    from pydantic import Field

    from backend.util.poster_self_heal.config import PosterSelfHealConfig

    return {
        "poster_self_heal": (
            PosterSelfHealConfig,
            Field(default_factory=PosterSelfHealConfig),
        ),
    }


def tables():
    from backend.util.database.poster_heal_review import poster_heal_review_table

    return [poster_heal_review_table()]


def notification_formatters():
    from backend.util.poster_self_heal.notify import format_poster_self_heal

    return {
        "poster_self_heal": {"formatter": format_poster_self_heal, "type": "embedded"},
    }

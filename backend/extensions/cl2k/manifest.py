# backend/extensions/cl2k/manifest.py
"""Self-registration manifest for the CL2K poster maker.

Discovered by backend/extensions/__init__.py. Every hook imports its
payload lazily — manifests are imported while core modules (config,
schema) are still initialising, so module-level imports here would risk
circular imports.
"""


def available():
    """True only when the renderer's deps import — find_spec can't tell a
    pip-present wand from one whose libMagickWand is missing."""
    try:
        import psd_tools  # noqa: F401
        import wand.image  # noqa: F401
    except ImportError:
        return False
    return True


def routers():
    from backend.api.cl2k_maker import router

    return [router]


# No modules() hook: the CL2K maker is config-only — generation is on-demand from
# the maker page (via the API), so there is no batch run to register, schedule, or
# surface in Jobs. Its config page comes from config_fields() below.


def config_fields():
    from pydantic import Field

    from backend.util.cl2k.config import Cl2kMakerConfig

    return {
        "cl2k_maker": (Cl2kMakerConfig, Field(default_factory=Cl2kMakerConfig)),
    }


def tables():
    from backend.util.database.cl2k_generated import cl2k_generated_table

    return [cl2k_generated_table()]


def stream_prefixes():
    # The /plex-art proxy is loaded by <img>, which can only authenticate with a
    # short-lived stream token in the URL — so its route joins the allowlist.
    return ("/api/cl2k-maker/plex-art",)

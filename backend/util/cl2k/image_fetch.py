"""Select + download CL2K render inputs (textless backdrop + sharp clear logo).

Logo source chain is TMDB -> fanart.tv -> (caller falls back to a generated
text-logo via renderer.generate_text_logo). The selection here encodes the two
hard-won rules:

- **Backdrops must be textless** — prefer language-neutral art (TMDB
  ``iso_639_1`` null/empty) so we never composite a credits-laden poster.
- **Logos are chosen by resolution**, not popularity — TMDB's highest-*voted*
  logo can be a soft low-res upload (a 797px Matrix logo outvoted the sharp
  2000px one). Resolution-first keeps logos crisp when scaled to the 600px box.

The selection functions are pure (they take the raw TMDB ``images`` lists), so
they are unit-testable without network or the TMDB client. ``download`` is a
thin fetch of the original-resolution CDN asset (no key needed for images).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

TMDB_IMAGE_CDN = "https://image.tmdb.org/t/p/original"


def select_backdrop(
    backdrops: List[Dict[str, Any]],
) -> Optional[str]:
    """Return the best *textless* backdrop ``file_path`` (top vote), or None.

    Language-neutral art (no ``iso_639_1``) is strongly preferred; only if none
    exists do we fall back to the highest-voted of whatever is available.
    """
    if not backdrops:
        return None
    textless = [b for b in backdrops if not b.get("iso_639_1")]
    pool = textless or backdrops
    pool = sorted(
        pool,
        key=lambda b: (b.get("vote_average", 0), b.get("vote_count", 0)),
        reverse=True,
    )
    return pool[0].get("file_path")


def select_logo(
    logos: List[Dict[str, Any]],
    lang: str = "en",
) -> Optional[str]:
    """Return the highest-*resolution* logo ``file_path`` (lang + PNG preferred).

    Resolution drives sharpness, so we rank by width (vote as tiebreaker) rather
    than by popularity.
    """
    if not logos:
        return None
    in_lang = [lg for lg in logos if lg.get("iso_639_1") == lang]
    base = in_lang or logos
    png = [lg for lg in base if str(lg.get("file_path", "")).lower().endswith(".png")]
    pool = png or base
    pool = sorted(
        pool,
        key=lambda lg: (lg.get("width", 0), lg.get("vote_average", 0)),
        reverse=True,
    )
    return pool[0].get("file_path")


def _is_allowed_image_host(url: str) -> bool:
    """Allow only the known image CDNs (TMDB + fanart.tv).

    ``download`` accepts absolute URLs that originate from request data
    (``backdrop_path`` / ``logo_path``), so without a host allowlist the server
    could be coerced into fetching arbitrary internal URLs (SSRF — e.g. cloud
    metadata). Restricting to the hosts the maker legitimately uses closes that.
    """
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return (
        host == "image.tmdb.org"
        or host == "assets.fanart.tv"
        or host.endswith(".fanart.tv")
    )


def download(file_path: str, session=None) -> bytes:
    """Download an image by TMDB path or absolute URL.

    A bare TMDB ``file_path`` is fetched at original resolution from the CDN (no
    API key needed); an absolute ``http(s)`` URL (e.g. a fanart.tv logo) is
    fetched as-is — but only from the allowed image hosts (TMDB / fanart.tv), so a
    crafted ``logo_path`` / ``backdrop_path`` can't turn this into an SSRF.
    """
    import requests

    url = file_path if file_path.startswith("http") else TMDB_IMAGE_CDN + file_path
    if not _is_allowed_image_host(url):
        from urllib.parse import urlparse

        raise ValueError(
            f"refusing to fetch image from disallowed host: {urlparse(url).hostname!r}"
        )
    resp = (session or requests).get(url, timeout=15)
    resp.raise_for_status()
    return resp.content


def select_cl2k_inputs(
    images: Dict[str, Any],
    lang: str = "en",
) -> Dict[str, Optional[str]]:
    """Pick backdrop + logo ``file_path``s from a TMDB ``/images`` payload.

    Returns ``{"backdrop": path|None, "logo": path|None}``. The fanart.tv logo
    fallback and the generated-text-logo fallback are applied by the caller when
    ``logo`` is None (they require the fanart client / renderer, wired later).
    """
    return {
        "backdrop": select_backdrop(images.get("backdrops", [])),
        "logo": select_logo(images.get("logos", []), lang=lang),
    }

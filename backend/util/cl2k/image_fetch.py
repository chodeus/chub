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

import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from backend.util.cl2k import geometry as geo

TMDB_IMAGE_CDN = "https://image.tmdb.org/t/p/original"


def select_backdrop(
    backdrops: List[Dict[str, Any]],
    min_height: int = geo.CANVAS_H,
) -> Optional[str]:
    """Return the best *textless* backdrop ``file_path``, or None.

    The backdrop *is* the whole poster background — cover-resized to the 1000×1500
    canvas — so resolution matters as much as curation. Selection is therefore
    two-tier:

    1. Among textless candidates, prefer those tall enough to fill the canvas
       without upscaling (``height >= min_height``) and rank *those* by vote, so
       TMDB's curation decides among the sharp options.
    2. If none are tall enough, fall back to the highest-resolution candidate so
       we upscale as little as possible.

    Language-neutral art (no ``iso_639_1``) is strongly preferred; only if none
    exists do we consider language-tagged backdrops.
    """
    if not backdrops:
        return None
    textless = [b for b in backdrops if not b.get("iso_639_1")]
    pool = textless or backdrops
    sharp = [b for b in pool if b.get("height", 0) >= min_height]
    if sharp:
        ranked = sorted(
            sharp,
            key=lambda b: (b.get("vote_average", 0), b.get("vote_count", 0)),
            reverse=True,
        )
    else:
        # Nothing fills the canvas natively — minimise upscaling by taking the
        # largest available (vote only as a tiebreaker between equal sizes).
        ranked = sorted(
            pool,
            key=lambda b: (
                b.get("height", 0),
                b.get("width", 0),
                b.get("vote_average", 0),
            ),
            reverse=True,
        )
    return ranked[0].get("file_path")


def select_logo(
    logos: List[Dict[str, Any]],
    lang: str = "en",
) -> Optional[str]:
    """Return the highest-*resolution* logo ``file_path`` (lang preferred).

    Resolution drives sharpness, so vectors outrank everything (an SVG is
    rasterized at ~2000px content width downstream — sharper than any raster),
    then the widest PNG (vote as tiebreaker) rather than popularity.
    """
    if not logos:
        return None
    in_lang = [lg for lg in logos if lg.get("iso_639_1") == lang]
    base = in_lang or logos
    svg = [lg for lg in base if str(lg.get("file_path", "")).lower().endswith(".svg")]
    if svg:
        svg = sorted(
            svg,
            key=lambda lg: (lg.get("vote_average", 0), lg.get("width", 0)),
            reverse=True,
        )
        return svg[0].get("file_path")
    png = [lg for lg in base if str(lg.get("file_path", "")).lower().endswith(".png")]
    pool = png or base
    pool = sorted(
        pool,
        key=lambda lg: (lg.get("width", 0), lg.get("vote_average", 0)),
        reverse=True,
    )
    return pool[0].get("file_path")


def _plex_netlocs() -> set:
    """host:port of every configured Plex instance.

    The Plex artwork source returns image URLs on the user's own Plex server, so
    those endpoints must pass the SSRF allowlist below. Matching the exact
    ``host:port`` (not just the hostname) keeps the opening as tight as possible
    — only the Plex server the user configured, not other services on that host.
    Read from config each call (cheap; config is cached) so a newly-added
    instance is honoured without a restart."""
    from urllib.parse import urlparse

    try:
        from backend.util.config import load_config

        plex = getattr(load_config().instances, "plex", {}) or {}
        out = set()
        for cfg in plex.values():
            nl = (urlparse(getattr(cfg, "url", "") or "").netloc or "").lower()
            if nl:
                out.add(nl)
        return out
    except Exception:
        return set()


def _is_allowed_image_host(url: str) -> bool:
    """Allow only the known image CDNs (TMDB + fanart.tv + Plex's own CDN) and
    the user's own configured Plex server(s).

    ``download`` accepts absolute URLs that originate from request data
    (``backdrop_path`` / ``logo_path``), so without a host allowlist the server
    could be coerced into fetching arbitrary internal URLs (SSRF — e.g. cloud
    metadata). Restricting to the hosts the maker legitimately uses closes that;
    the user's Plex server is matched by exact host:port from config.

    ``*.plex.tv`` is Plex's own infrastructure: the Plex artwork picker returns
    remote-provider art (tmdb/fanarttv/gracenote) as absolute
    ``metadata-static.plex.tv`` URLs, which must be fetchable or selecting any
    non-uploaded Plex logo 500s. The same applies to every other agent CDN Plex
    hands back as an absolute URL: ``artworks.thetvdb.com`` (TheTVDB, common on
    shows) and ``m.media-amazon.com`` / ``*.ssl-images-amazon.com`` (IMDb art).
    A live audit of the artwork picker across movies + shows surfaced exactly
    these five provider CDNs (tmdb / fanart.tv / plex.tv / thetvdb.com /
    media-amazon.com) plus the user's own Plex — anything else must be added here
    or selecting that art 500s ("refusing to fetch image from disallowed host").
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        host == "image.tmdb.org"
        or host == "assets.fanart.tv"
        or host.endswith(".fanart.tv")
        or host == "plex.tv"
        or host.endswith(".plex.tv")
        or host == "thetvdb.com"
        or host.endswith(".thetvdb.com")
        or host.endswith(".media-amazon.com")
        or host.endswith(".ssl-images-amazon.com")
    ):
        return True
    return (parsed.netloc or "").lower() in _plex_netlocs()


def strip_plex_token(value: Optional[str]) -> Optional[str]:
    """Drop the X-Plex-Token query param so the admin token is never persisted at
    rest (e.g. in cl2k_generated.backdrop_path). download() re-mints it on fetch."""
    if not isinstance(value, str) or "x-plex-token" not in value.lower():
        return value
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(value)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() != "x-plex-token"
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def _plex_token_for(netloc: str) -> Optional[str]:
    """The X-Plex-Token (Plex instance api key) for the configured Plex server
    matching ``netloc``."""
    from urllib.parse import urlparse

    try:
        from backend.util.config import load_config

        plex = getattr(load_config().instances, "plex", {}) or {}
        for cfg in plex.values():
            if (urlparse(getattr(cfg, "url", "") or "").netloc or "").lower() == netloc:
                return getattr(cfg, "api", None) or None
    except Exception:
        return None
    return None


def _with_plex_token(url: str) -> str:
    """Re-mint the X-Plex-Token for a tokenless Plex-server URL (a persisted
    backdrop_path has it stripped). No-op for non-Plex hosts or already-tokened URLs."""
    from urllib.parse import urlparse

    if "x-plex-token" in url.lower():
        return url
    netloc = (urlparse(url).netloc or "").lower()
    if netloc not in _plex_netlocs():
        return url
    token = _plex_token_for(netloc)
    if not token:
        return url
    return f"{url}{'&' if '?' in url else '?'}X-Plex-Token={token}"


def _unwrap_proxy(file_path: str) -> str:
    """A CL2K plex-art proxy path (``/api/cl2k-maker/plex-art?src=<url>``) is the
    browser-facing form of local Plex art; when the frontend posts the chosen art
    back for a render, unwrap ``?src=`` to the real (tokenless) Plex URL so the
    server-side fetch hits Plex directly (and re-mints the token). No-op otherwise."""
    if not file_path.startswith("/api/cl2k-maker/plex-art?"):
        return file_path
    from urllib.parse import parse_qs, urlparse

    src = parse_qs(urlparse(file_path).query).get("src", [""])[0]
    return src or file_path


# Recently downloaded originals, keyed by final URL. Live-preview slider tweaks
# re-render the same backdrop/logo over and over; without this every /preview
# request re-pulled the multi-MB original from the CDN, dominating preview
# latency. Bounded by total bytes (originals are big), LRU eviction.
_DL_CACHE: OrderedDict[str, bytes] = OrderedDict()
_DL_CACHE_LOCK = threading.Lock()
_DL_CACHE_MAX_BYTES = 64 * 1024 * 1024


def _dl_cache_get(url: str) -> Optional[bytes]:
    with _DL_CACHE_LOCK:
        data = _DL_CACHE.get(url)
        if data is not None:
            _DL_CACHE.move_to_end(url)
        return data


def _dl_cache_put(url: str, data: bytes) -> None:
    if len(data) > _DL_CACHE_MAX_BYTES:
        return
    with _DL_CACHE_LOCK:
        _DL_CACHE[url] = data
        _DL_CACHE.move_to_end(url)
        total = sum(len(v) for v in _DL_CACHE.values())
        while total > _DL_CACHE_MAX_BYTES and _DL_CACHE:
            _, evicted = _DL_CACHE.popitem(last=False)
            total -= len(evicted)


def download(file_path: str, session=None) -> bytes:
    """Download an image by TMDB path or absolute URL.

    A bare TMDB ``file_path`` is fetched at original resolution from the CDN (no
    API key needed); an absolute ``http(s)`` URL (e.g. a fanart.tv logo) is
    fetched as-is — but only from the allowed image hosts (TMDB / fanart.tv), so a
    crafted ``logo_path`` / ``backdrop_path`` can't turn this into an SSRF.

    Successful fetches are kept in a small in-memory LRU so consecutive previews
    of the same art don't re-download it. Calls with an explicit ``session``
    bypass the cache (they control their own transport/fixtures).
    """
    import requests

    file_path = _unwrap_proxy(file_path)
    url = file_path if file_path.startswith("http") else TMDB_IMAGE_CDN + file_path
    if not _is_allowed_image_host(url):
        from urllib.parse import urlparse

        raise ValueError(
            f"refusing to fetch image from disallowed host: {urlparse(url).hostname!r}"
        )
    # Re-mint the Plex token for a persisted (token-stripped) backdrop_path.
    url = _with_plex_token(url)
    if session is None:
        cached = _dl_cache_get(url)
        if cached is not None:
            return cached
    getter = session or requests
    cache_key = url
    # Don't auto-follow redirects: an allowed host that 3xx-redirects to an internal
    # address would defeat _is_allowed_image_host. Re-validate the host every hop.
    resp = getter.get(url, timeout=15, allow_redirects=False)
    hops = 0
    while getattr(resp, "is_redirect", False) and hops < 4:
        from urllib.parse import urljoin, urlparse

        nxt = urljoin(url, resp.headers.get("Location", ""))
        if not _is_allowed_image_host(nxt):
            raise ValueError(
                f"refusing to follow redirect to disallowed host: {urlparse(nxt).hostname!r}"
            )
        url = _with_plex_token(nxt)
        resp = getter.get(url, timeout=15, allow_redirects=False)
        hops += 1
    resp.raise_for_status()
    if session is None:
        _dl_cache_put(cache_key, resp.content)
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

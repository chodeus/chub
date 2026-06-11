"""Build ID-tagged CL2K poster filenames (the "idarr" naming piece).

Reproduces the TPDB / Trash-Guides convention that the DAPS guide requires and
that real CL2K posters use, e.g.::

    The Matrix (1999) {tmdb-603} {imdb-tt0133093}.jpg
    The Matrix Collection {tmdb-2344}.jpg
    Breaking Bad (2008) {tvdb-81189} - Season 01.jpg
    Breaking Bad (2008) {tvdb-81189} - Specials.jpg

ID tags are space-separated in tmdb -> tvdb -> imdb order (only those present).
Collections carry no year; seasons append `` - Season {NN}`` — the Kometa/Drazzilb
" - Season " form that real CL2K community posters use (CHUB's season_number_regex
also accepts the ``_Season`` variant, but the spaced form matches creators' files).
Season 0 is written as `` - Specials`` instead of `` - Season 00`` to match the
community-maker convention (both parse back to season 0).
Illegal filename characters are stripped via the shared ``illegal_chars_regex``.
"""

from __future__ import annotations

from typing import Optional

from backend.util.constants import illegal_chars_regex


def _safe(title: str) -> str:
    """Strip filesystem-illegal characters from a title."""
    return illegal_chars_regex.sub("", title or "").strip()


def _id_tags(
    tmdb_id: Optional[int],
    tvdb_id: Optional[int],
    imdb_id: Optional[str],
) -> str:
    tags = []
    if tmdb_id:
        tags.append(f"{{tmdb-{tmdb_id}}}")
    if tvdb_id:
        tags.append(f"{{tvdb-{tvdb_id}}}")
    if imdb_id:
        tags.append(f"{{imdb-{imdb_id}}}")
    return " ".join(tags)


def build_poster_filename(
    *,
    kind: str,
    title: str,
    year: Optional[int] = None,
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    season_number: Optional[int] = None,
    ext: str = ".jpg",
    asset_suffix: str = "",
) -> str:
    """Return the ID-tagged poster filename for a media item.

    ``kind`` is movie / show / collection / season. Collections omit the year;
    seasons append `` - Season {NN}`` to the show base name (the spaced Kometa/
    Drazzilb form that matches hand-made CL2K posters). Season 0 is the Specials
    season and is written as `` - Specials`` instead. Year-based "seasons" (e.g.
    Formula 1) just pass the year through as the number → `` - Season 2026``.

    ``asset_suffix`` appends an additional-asset tag before the extension (e.g.
    `` - SquareArt`` / `` - Logo``) so the file is parsed as that asset type by the
    asset_renamerr naming regex, e.g. ``The Matrix (1999) {tmdb-603} - SquareArt.jpg``.
    """
    title = _safe(title)
    tags = _id_tags(tmdb_id, tvdb_id, imdb_id)

    if kind == "collection":
        base = f"{title} {tags}".strip()
    else:
        base = f"{title} ({year})" if year else title
        if tags:
            base = f"{base} {tags}"

    if kind == "season" and season_number is not None:
        # Season 0 is the Specials season — write the `- Specials` form that
        # community CL2K makers use (Kometa/Plex and CHUB's season_number_regex
        # both read it back as season 0). Numbered seasons keep ` - Season NN`.
        base = f"{base} - Specials" if season_number == 0 else f"{base} - Season {season_number:02d}"
    return f"{base}{asset_suffix}{ext}"

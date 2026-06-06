"""Build ID-tagged CL2K poster filenames (the "idarr" naming piece).

Reproduces the TPDB / Trash-Guides convention that the DAPS guide requires and
that real CL2K posters use, e.g.::

    The Matrix (1999) {tmdb-603} {imdb-tt0133093}.jpg
    The Matrix Collection {tmdb-2344}.jpg
    Breaking Bad (2008) {tvdb-81189}_Season01.jpg

ID tags are space-separated in tmdb -> tvdb -> imdb order (only those present).
Collections carry no year; seasons append ``_Season{NN}`` like poster_renamerr.
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
) -> str:
    """Return the ID-tagged poster filename for a media item.

    ``kind`` is movie / show / collection / season. Collections omit the year;
    seasons append ``_Season{NN}`` to the show base name.
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
        return f"{base}_Season{season_number:02d}{ext}"
    return f"{base}{ext}"

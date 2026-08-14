"""
Candidate assets for a media row — the shared gather + rank behind the manual
poster picker and its artwork counterpart.

Returns scored rows only; each caller owns the JSON shape it renders.
"""

import difflib
import json
from typing import Any, Dict, List, Optional, Tuple

from backend.util.helper import is_match
from backend.util.normalization import normalize_titles


def rank_candidates(
    db: Any,
    row: Dict[str, Any],
    asset_type: Optional[str],
    image_type: Optional[str] = "poster",
    limit: int = 24,
) -> List[Tuple[Dict[str, Any], bool, float, str]]:
    """Best-first (row, would_match, similarity, reason) tuples for a media row."""
    season_number = row.get("season_number")
    try:
        alts = json.loads(row.get("alternate_titles") or "[]")
    except (ValueError, TypeError):
        alts = []
    search_titles = [row.get("title")] + [a for a in alts if a]
    row_norm = row.get("normalized_title") or normalize_titles(row.get("title") or "")

    seen = set()
    gathered = []
    for st in search_titles:
        # Checked per title too: an inner break alone lets each alternate
        # title add another 800 rows before anything is scored.
        if len(gathered) >= 800:
            break
        for c in db.poster.get_candidates_by_prefix(
            st or "", asset_type=asset_type, image_type=image_type
        ):
            f = c.get("file")
            if f and f not in seen:
                seen.add(f)
                gathered.append(c)
            if len(gathered) >= 800:
                break

    # Score every candidate by title similarity. The prefix bucket alone is
    # NOT relevance — without this, the picker showed every poster sharing
    # the first 3 chars ("str" → Striptease, Strays, …) regardless of the
    # title. Rank real matches first, then by similarity, and drop posters
    # that neither match nor resemble the title.
    scored = []
    for c in gathered:
        cs = c.get("season_number")
        if season_number is not None and cs != season_number:
            continue
        if season_number is None and cs is not None:
            continue
        matched, reason = is_match(c, row)
        sim = difflib.SequenceMatcher(
            None, row_norm, c.get("normalized_title") or ""
        ).ratio()
        scored.append((bool(matched), sim, c, reason))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    ranked: List[Tuple[Dict[str, Any], bool, float, str]] = []
    for matched, sim, c, reason in scored:
        # Real matches always show; non-matching extras only if the title
        # genuinely resembles (drops same-prefix-but-unrelated noise).
        if not matched and sim < 0.6:
            continue
        ranked.append((c, matched, sim, reason))
        if len(ranked) >= limit:
            break
    return ranked

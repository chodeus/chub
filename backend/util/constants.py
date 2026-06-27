import re
from typing import List, Pattern, Set

# Matches a season/specials *suffix* tag — "- Season 1", "_Season01", or
# "- Specials"/"_Specials" (Specials returns season 0 via a None capture).
# The leading `(?:\s*-\s*|_)` delimiter is REQUIRED: a real season poster in
# the Kometa/Drazzilb naming scheme always separates the tag from the title
# with " - " or "_" (e.g. "Show Name (2020) - Season 1.jpg"). Without the
# delimiter, a bare "Season <n>" embedded in a *movie title* ("Open Season 2",
# "Open Season 3") was being eaten as a TV season marker — mutilating the
# title to "Open" and stamping season_number=2, which broke both asset search
# (normalized_title became "open") and poster matching against the Radarr row.
# `Specials` stays plural-only with a trailing `\b` so singular "Special" in a
# movie title ("X-Men First Class 35mm Special") is never matched.
#
# The `^` alternative additionally accepts a tag at the very start of the name
# so folder-based layouts still work — a bare "Season01.jpg" file or a "Season
# 01" folder (chub searches both the filename and the folder). "Open Season 2"
# matches neither the delimiter nor the start anchor, so it stays a movie.
# Whitespace runs are bounded (``\s{0,8}`` not ``\s*``) so the delimiter can't
# cause polynomial-time backtracking (ReDoS) on a crafted title — no real
# filename has 8+ consecutive spaces around the season delimiter.
# The delimiter prefix is factored out (one ``(?:^|…)`` instead of two) so there is
# a single, matchable start anchor — equivalent to the old two-branch form but
# without the spurious "unmatchable caret" the duplicated anchor produced.
season_number_regex = re.compile(
    r"(?:^|\s{0,8}-\s{0,8}|_)(?:Season\s{0,8}(\d{1,4})|Specials\b)",
    re.IGNORECASE,
)

# Matches an additional-asset type tag suffix — " - Logo"/"_Logo", "- SquareArt",
# "- Background", "- Banner" (case-insensitive), capturing the type as group 1.
# The leading `(?:\s*-\s*|_)` delimiter is REQUIRED (same rationale as
# season_number_regex): a real asset file in the Kometa/Drazzilb scheme always
# separates the type tag from the title with " - " or "_" (e.g.
# "Show Name (2020) - Logo.png", "Movie (1999) {tmdb-1} - SquareArt.png"). The
# delimiter requirement plus a trailing `\b` keeps a bare "Logo"/"Background"
# inside a real title (a movie literally named "Logo", "Open Background") from
# being mistaken for an asset-type tag. Used by asset_renamerr to (a) detect the
# image_type and (b) strip the tag before normalising the title so the asset's
# match key equals the same media's poster key.
#
# Banner is matched on purpose even though it is NOT a processable asset type
# (no Plex upload API, not read by Kometa — see asset_renamerr.ALL_ASSET_TYPES):
# recognising "Movie (2020) - Banner.png" as a banner means it's classified and
# ignored rather than mis-parsed as a poster titled "Movie - Banner".
asset_type_regex = re.compile(
    r"(?:\s{0,8}-\s{0,8}|_)(Logo|SquareArt|Background|Banner)\b", re.IGNORECASE
)

# Matches the literal "Season " followed by 1–4 digits (e.g. "Season 1", "Season 12", up to "Season 9999"), capturing those digits as group 1
season_regex: str = r"Season (\d{1,4})"

# Matches strings like "E01" or "e5", capturing 1–2 digits as the episode number
episode_regex: str = r"(?:E|e)(\d{1,2})"

# Matches any text (group 1) followed by a space and a 4-digit year in parentheses (group 2), e.g. "Movie Title (2022)"
folder_year_regex: Pattern = re.compile(r"(.*)\s\((\d{4})\)")

# Matches an optional space, a 4-digit year in parentheses (captured as group 1), ensures “Collection” does not appear later, and consumes any trailing text
year_regex: Pattern = re.compile(r"\s?\((\d{4})\)(?!.*Collection).*")

# Matches a parenthesized all-zero "year" placeholder that *arr writes when the
# real release year is unknown (unaired/unannounced), e.g. "The Savant (0)".
# year_regex above only strips a 4-digit year, so a 1–3 digit "(0)"/"(00)"/"(000)"
# would otherwise survive as a bare "0" glued to the title ("thesavant0") and break
# title matching — stranding the poster, and looping if cleanup removes the folder
# while the renamer recreates it. Stripped alongside year_regex during normalization.
unknown_year_regex: Pattern = re.compile(r"\s*\(0+\)")

# Matches one or more illegal filename characters—including < > : " / \ | ? * and control characters U+0000–U+001F
illegal_chars_regex: Pattern = re.compile(r"[<>:\"/\\|?*\x00-\x1f]+")

# Matches one or more characters that are not letters (A–Z, a–z), digits (0–9), or whitespace, i.e., special symbols and punctuation
remove_special_chars: Pattern = re.compile(r"[^a-zA-Z0-9\s]+")

# Matches any path ending in “/Title (YYYY)” (possibly with characters after), capturing the title (everything after the last slash up to the space) as group 1 and the 4-digit year as group 2
title_regex: str = r".*\/([^/]+)\s\((\d{4})\).*"

# matches "tmdbid 12345", "tmdbid12345", "tmdb-12345", "tmdb_12345", "tmdb 12345"
tmdb_id_regex = re.compile(r"(?i)\btmdb(?:id[-_\s]*|[-_\s])(\d+)\b")

# matches "tvdbid 67890", "tvdbid67890", "tvdb-67890", "tvdb_67890", "tvdb 67890"
tvdb_id_regex = re.compile(r"(?i)\btvdb(?:id[-_\s]*|[-_\s])(\d+)\b")

# Matches strings like "imdb-tt1234567", "imdb_tt1234567", or "imdb tt1234567", capturing the "tt" plus digits as the IMDb ID
imdb_id_regex: Pattern = re.compile(r"imdb[-_\s](tt\d+)")

# Matches a MusicBrainz id tag: "mbid-<uuid>", "mbid_<uuid>", "mbid <uuid>",
# "mbid:<uuid>" (case-insensitive), capturing the canonical UUID. Used to
# identify custom music art (artist/album) by MusicBrainz id in a filename or
# folder, mirroring the tmdb/tvdb id tags.
mbid_id_regex: Pattern = re.compile(
    r"(?i)\bmbid[-_\s:]*"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b"
)

# Remove bracketed blocks containing TMDB, TVDB, or IMDb IDs. The tmdb/tvdb
# branches accept the optional "id" suffix (e.g. {tvdbid-123}) so block
# stripping stays consistent with tmdb_id_regex/tvdb_id_regex extraction —
# otherwise extract_ids pulled the id but the block was left in the title,
# polluting normalized_title with "tvdbid123".
id_content_regex = re.compile(
    r"\s*[\{\[]\s*(?:"
    r"tmdb(?:id[-_\s]*|[-_\s])\d+|"
    r"tvdb(?:id[-_\s]*|[-_\s])\d+|"
    r"imdb(?:[-_\s](?:tt)?\d+)|"
    r"mbid[-_\s:]*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r")\s*[\}\]]",
    flags=re.IGNORECASE,
)

words_to_remove: List[str] = [
    "(US)",
    "(UK)",
    "(AU)",
    "(CA)",
    "(NZ)",
    "(FR)",
    "(NL)",
    "DC's",
]

common_words: Set[str] = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to"}

prefixes: List[str] = [
    "The",
    "A",
    "An",
]

suffixes: List[str] = [
    "Collection",
    "Saga",
]

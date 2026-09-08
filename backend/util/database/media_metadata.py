"""Metadata-completeness rules for media_cache, mixed into MediaCache."""

from typing import List

from .db_base import DatabaseBase

# Columns find_incomplete_metadata may test, and the subset stored as INTEGER
# (they can't hold '', so they compare against NULL/0 instead).
INCOMPLETE_METADATA_FIELDS = frozenset(
    {
        "rating",
        "studio",
        "language",
        "genre",
        "runtime",
        "edition",
        "tmdb_id",
        "tvdb_id",
        "imdb_id",
        "year",
    }
)

def is_missing_value(field: str, value) -> bool:
    """True when `value` is missing for `field`."""
    # One rule for every field: year is stored TEXT but arrives as 0 from the
    # ARRs when unknown, so an INT/TEXT split silently kept those rows complete.
    return value is None or value in ("", "0", 0)


# Fields the ARR normalize layer never populates for a given asset_type, so
# flagging them as "missing" is a false positive. Radarr has no tvdbId,
# Sonarr has no tmdbId, Lidarr (artist) uses MusicBrainz IDs and leaves
# tmdb/tvdb/imdb + rating/runtime/language/edition as None by design.
NEVER_POPULATED_FIELDS = {
    "movie": {"tvdb_id"},
    "show": {"tmdb_id"},
    "artist": {
        "tmdb_id",
        "tvdb_id",
        "imdb_id",
        "rating",
        "runtime",
        "language",
        "edition",
    },
}
# asset_types with their own expected-field rules; anything else matches
# find_incomplete_metadata's catch-all clause.
_KNOWN_ASSET_TYPES = ("movie", "show", "artist")


class MetadataCompletenessMixin(DatabaseBase):
    """Queries for media_cache rows missing metadata their asset_type can hold."""

    @staticmethod
    def _empty_field_clauses(fields: List[str]) -> str:
        """OR-joined "is null or blank" test for each field."""
        # SQL mirror of is_missing_value — keep in sync. `= 0` also matches the
        # text '0' by column affinity, which is how year arrives.
        return " OR ".join(
            f"({f} IS NULL OR {f} = '' OR {f} = 0)" for f in fields
        )

    def find_incomplete_metadata(
        self, fields: List[str], limit: int = 200, offset: int = 0
    ) -> list:
        """Return rows missing any of `fields` that their asset_type can populate."""
        # Field names are interpolated into SQL — drop anything off the
        # column allow-list before building the clause.
        requested = [f for f in fields if f in INCOMPLETE_METADATA_FIELDS]
        if not requested:
            return []

        # One clause per known asset_type, using only the fields that type can
        # populate; a catch-all keeps unrecognised types matching on the lot.
        subclauses = []
        params: list = []
        for atype in _KNOWN_ASSET_TYPES:
            never = NEVER_POPULATED_FIELDS.get(atype, set())
            effective = [f for f in requested if f not in never]
            if not effective:
                continue
            subclauses.append(
                f"(asset_type = ? AND ({self._empty_field_clauses(effective)}))"
            )
            params.append(atype)

        unknown_placeholders = ",".join(["?"] * len(_KNOWN_ASSET_TYPES))
        subclauses.append(
            f"(asset_type NOT IN ({unknown_placeholders}) "
            f"AND ({self._empty_field_clauses(requested)}))"
        )
        params.extend(_KNOWN_ASSET_TYPES)

        where = " OR ".join(subclauses)
        return (
            self.execute_query(
                f"SELECT * FROM media_cache WHERE {where} "
                "ORDER BY title ASC, id ASC LIMIT ? OFFSET ?",
                (*params, limit, offset),
                fetch_all=True,
            )
            or []
        )

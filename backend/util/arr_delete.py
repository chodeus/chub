"""Find a cached row's own *arr instance, and delete its item there."""

from typing import Any, Dict, NamedTuple, Optional, Tuple

from backend.util.arr import ARRPermanentError, create_arr_client
from backend.util.config import load_config
from backend.util.public_error import failure_text

ARR_TYPES = ("radarr", "sonarr", "lidarr")

# The rows whose arr_id names exactly the item an *arr delete removes. A Sonarr
# season row carries its series' id and a Lidarr album row an album id, which
# the artist endpoint would read as some other artist.
_DELETABLE = {("radarr", "movie"), ("sonarr", "show")}


def instance_detail(instances: Any, row: Dict[str, Any]) -> Any:
    """The row's own instance config: under its stored type, else the first name match."""
    # Names are unique only within a type, so a stored type is never second-guessed.
    kind = row.get("source")
    kinds = (kind,) if kind in ARR_TYPES else ARR_TYPES
    for arr_type in kinds:
        detail = (getattr(instances, arr_type, None) or {}).get(row.get("instance_name"))
        if detail is not None:
            return detail
    return None


class DeleteFailure(NamedTuple):
    reason: str
    # 409: CHUB refused before asking the *arr; 502: the *arr call failed.
    status: int


class ArrDeleter:
    """Deletes rows' items from their *arr with one config read and client per instance."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger
        self._instances: Any = None
        self._clients: Dict[Tuple[str, str], Any] = {}

    def __enter__(self) -> "ArrDeleter":
        return self

    def __exit__(self, *exc: Any) -> None:
        for client in self._clients.values():
            session = getattr(client, "session", None)
            if session is not None:
                try:
                    session.close()
                except Exception:  # noqa: S110 - cleanup must not mask the real error
                    pass

    def delete(
        self, item: Dict[str, Any], delete_files: bool, add_exclusion: bool
    ) -> Optional[DeleteFailure]:
        """None once the item is gone from its *arr (or has no *arr to leave)."""
        name, arr_id, kind = item.get("instance_name"), item.get("arr_id"), item.get("source")
        if not (name and arr_id):
            return self._unlinked(delete_files, "it is not linked to Radarr or Sonarr")
        if self._instances is None:
            self._instances = load_config().instances
        detail = instance_detail(self._instances, item)
        if not (detail and detail.url and detail.api):
            return self._unlinked(delete_files, f"{name} is not configured")
        if (kind, item.get("asset_type")) not in _DELETABLE or item.get("season_number"):
            return DeleteFailure(
                "only a whole movie or series can be deleted from Radarr or Sonarr", 409
            )
        client = self._client(kind, name, detail)
        if client is None:
            return DeleteFailure(f"could not connect to {name}", 502)
        if str(getattr(client, "instance_type", "")).lower() != kind:
            return DeleteFailure(f"{name} is not a {kind.capitalize()} instance", 409)
        try:
            confirmed = client.delete_media(arr_id, delete_files, add_exclusion)
        except ARRPermanentError:
            # A 404: the item is already gone, which is what was asked for.
            self.logger.info(f"{name} no longer has {kind} item {arr_id}")
            return None
        except Exception as e:
            self.logger.error(f"Deleting {kind} item {arr_id} from {name} failed: {e}")
            return DeleteFailure(failure_text(f"Deleting from {name}", e), 502)
        # A request that runs out of retries returns None instead of raising.
        if not confirmed:
            return DeleteFailure(
                f"{name} did not confirm the delete — see the server log", 502
            )
        self.logger.info(
            f"Deleted {kind} item {arr_id} from {name} "
            f"(deleteFiles={delete_files}, exclusion={add_exclusion})"
        )
        return None

    def _client(self, kind: str, name: str, detail: Any) -> Any:
        key = (kind, name)
        if key not in self._clients:
            self._clients[key] = create_arr_client(
                url=detail.url, api=detail.api, logger=self.logger
            )
        return self._clients[key]

    @staticmethod
    def _unlinked(delete_files: bool, why: str) -> Optional[DeleteFailure]:
        """No *arr item to delete: fine for the row, a refusal if files were asked for."""
        if not delete_files:
            return None
        return DeleteFailure(f"{why}, so its files were not deleted", 409)

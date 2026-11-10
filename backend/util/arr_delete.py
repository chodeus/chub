"""Delete a cached row's item from its own *arr."""

from typing import Any, Dict, NamedTuple, Optional, Tuple

from backend.util.arr import ARRPermanentError, create_arr_client
from backend.util.arr_instances import instance_detail, row_kind, whole_item, wrong_client
from backend.util.config import load_config
from backend.util.public_error import failure_text


def _arr_key(row: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
    """What an *arr delete of ``row`` would remove; Lidarr album and artist ids overlap."""
    if not row.get("arr_id"):
        return None
    return (row_kind(row), row.get("instance_name"), row.get("asset_type"), row.get("arr_id"))


class ArrOutcome(NamedTuple):
    """``reason`` None: the row may go. ``deleted``: the *arr removed the item just now."""

    reason: Optional[str] = None
    # 409: CHUB refused before asking the *arr; 502: the *arr call failed.
    status: int = 200
    deleted: bool = False


class ArrDeleter:
    """Deletes rows' items from their *arr with one config read and client per instance."""

    def __init__(self, logger: Any, keep: Optional[Dict[str, Any]] = None) -> None:
        self.logger = logger
        # A duplicate row pointing at the kept row's *arr item is that item.
        self._kept = _arr_key(keep) if keep else None
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
                except Exception as e:  # cleanup must not mask the real error
                    self.logger.debug(f"Closing an *arr session failed: {e}")

    def delete(
        self, item: Dict[str, Any], delete_files: bool, add_exclusion: bool
    ) -> ArrOutcome:
        """Remove ``item`` from its *arr, or say why it was not."""
        name, arr_id, kind = item.get("instance_name"), item.get("arr_id"), row_kind(item)
        if not (name and arr_id):
            if delete_files:
                return ArrOutcome(
                    "it is not linked to Radarr, Sonarr or Lidarr, so its files were "
                    "not deleted",
                    409,
                )
            return ArrOutcome()
        if self._kept is not None and _arr_key(item) == self._kept:
            return ArrOutcome()
        if self._instances is None:
            self._instances = load_config().instances
        detail = instance_detail(self._instances, item)
        if not (detail and detail.url and detail.api):
            return ArrOutcome(f"{name} is not configured", 409)
        if not whole_item(item):
            return ArrOutcome(
                "only a whole movie, series or artist can be deleted from its *arr", 409
            )
        client = self._client(kind, name, detail)
        if client is None:
            return ArrOutcome(f"could not connect to {name}", 502)
        mismatch = wrong_client(client, kind, name)
        if mismatch:
            return ArrOutcome(mismatch, 409)
        try:
            confirmed = client.delete_media(arr_id, delete_files, add_exclusion)
        except ARRPermanentError:
            # A 404: the item is already gone, which is what was asked for.
            self.logger.info(f"{name} no longer has {kind} item {arr_id}")
            return ArrOutcome()
        except Exception as e:
            self.logger.error(f"Deleting {kind} item {arr_id} from {name} failed: {e}")
            return ArrOutcome(failure_text(f"Deleting from {name}", e), 502)
        # A request that runs out of retries returns None instead of raising.
        if not confirmed:
            return ArrOutcome(
                f"{name} did not confirm the delete — see the server log", 502
            )
        self.logger.info(
            f"Deleted {kind} item {arr_id} from {name} "
            f"(deleteFiles={delete_files}, exclusion={add_exclusion})"
        )
        return ArrOutcome(deleted=True)

    def _client(self, kind: str, name: str, detail: Any) -> Any:
        key = (kind, name)
        if key not in self._clients:
            self._clients[key] = create_arr_client(
                url=detail.url, api=detail.api, logger=self.logger
            )
        return self._clients[key]

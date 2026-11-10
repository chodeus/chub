"""Instance names must differ, even across service types: lookups by bare name rely on it."""

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

Entry = Tuple[str, str]  # (service type, instance name)


def _key(name: str) -> str:
    # Matches the loosest lookup (webhook_processor's .strip().lower()).
    return name.strip().lower()


def _entries(instances: Any) -> Dict[str, List[Entry]]:
    found: Dict[str, List[Entry]] = defaultdict(list)
    # Every dict field of InstancesConfig is a service type, so a new one is covered.
    for kind, named in vars(instances).items():
        if isinstance(named, dict):
            for name in named:
                found[_key(name)].append((kind, name))
    return found


def _clash(name: str, others: List[Entry]) -> str:
    named = " and ".join(f"{kind.capitalize()} instance '{n}'" for kind, n in others)
    return (
        f"'{name}' is the same name as the {named}; instance names must differ, "
        "ignoring case, even across services"
    )


def name_taken(
    instances: Any, name: str, kind: str, current: Optional[str] = None
) -> Optional[str]:
    """Why a ``kind`` instance (now ``current``, if renamed) may not be called ``name``."""
    others = [
        e for e in _entries(instances).get(_key(name), []) if e != (kind, current)
    ]
    return _clash(name, others) if others else None


def new_shared_name(before: Any, after: Any) -> Optional[str]:
    """Why ``after`` instances must not be saved: an instance newly sharing a name, or None."""
    # Only a new clash is refused, so a config that already has one still saves.
    old = {e for group in _entries(before).values() for e in group}
    for group in _entries(after).values():
        added = [e for e in group if e not in old]
        if added and len(group) > 1:
            return _clash(added[0][1], [e for e in group if e != added[0]])
    return None

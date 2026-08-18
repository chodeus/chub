# backend/util/poster_self_heal/notify.py
"""Discord formatter for poster_self_heal run summaries.

Registered via the extension manifest's notification_formatters() hook and merged
into notification_formatting.format_for_discord's registry under the
"poster_self_heal" module key.
"""

from typing import Any, Dict, List


def format_poster_self_heal(output: Any) -> List[Dict[str, Any]]:
    """Return Discord embed fields summarising a healer run."""
    o = output if isinstance(output, dict) else {}
    fields: List[Dict[str, Any]] = [
        {"name": "Posters scanned", "value": str(o.get("scanned", 0)), "inline": True},
    ]
    if o.get("applied"):
        fields.append(
            {"name": "Auto-applied", "value": str(o["applied"]), "inline": True}
        )
    if o.get("proposed"):
        fields.append(
            {"name": "Proposed (review)", "value": str(o["proposed"]), "inline": True}
        )
    if o.get("pending"):
        fields.append(
            {"name": "Needs a pick", "value": str(o["pending"]), "inline": True}
        )
    if o.get("failed"):
        fields.append(
            {"name": "Auto-apply failed", "value": str(o["failed"]), "inline": True}
        )
    fields.append(
        {"name": "Open for review", "value": str(o.get("open", 0)), "inline": True}
    )
    return fields

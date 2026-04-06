"""Command-style wrappers for operational alerts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import time
from typing import Any

from hi_agent.management.alerts import evaluate_operational_alerts


def cmd_alerts_from_signals(
    signals: dict[str, Any],
    *,
    severity_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build API-friendly alert payload rows from operational signals."""
    rows = evaluate_operational_alerts(signals)
    mapped_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        code = row["code"]
        mapped_rows.append(
            {
                "id": f"{code}:{index}",
                "code": code,
                "severity": (
                    str(severity_map[code])
                    if severity_map is not None and code in severity_map
                    else row["severity"]
                ),
                "message": row["message"],
                "status": "open",
            }
        )

    return {
        "command": "alerts_from_signals",
        "count": len(mapped_rows),
        "alerts": mapped_rows,
    }


def cmd_alerts_ack(
    alert_id: str,
    actor: str,
    *,
    now_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Build deterministic ack payload for one alert row."""
    normalized_alert_id = alert_id.strip()
    if not normalized_alert_id:
        raise ValueError("alert_id must be a non-empty string")
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("actor must be a non-empty string")

    return {
        "command": "alerts_ack",
        "alert_id": normalized_alert_id,
        "actor": normalized_actor,
        "acked_at": float((now_fn or time)()),
        "status": "acknowledged",
    }

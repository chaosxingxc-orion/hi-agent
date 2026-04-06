"""Command wrappers around ops governance checks."""

from __future__ import annotations

from typing import Any

from hi_agent.management.ops_governance import evaluate_ops_governance


def cmd_ops_governance_check(
    *,
    readiness: dict[str, Any],
    signals: dict[str, Any],
    slo_snapshot: dict[str, Any],
    alert_count: int = 0,
) -> dict[str, Any]:
    """Return command-style payload for governance decision."""
    decision = evaluate_ops_governance(
        readiness=readiness,
        signals=signals,
        slo_snapshot=slo_snapshot,
        alert_count=alert_count,
    )
    return {
        "command": "ops_governance_check",
        "decision": decision,
    }

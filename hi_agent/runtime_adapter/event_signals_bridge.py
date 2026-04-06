"""Bridge runtime event summaries to operational signal payloads."""

from __future__ import annotations

from collections.abc import Mapping


def build_signals_from_event_summary(
    summary: Mapping[str, object],
    *,
    backlog_threshold: int = 10,
) -> dict[str, object]:
    """Build reconcile-like operational signals from event summary payload.

    The mapping is intentionally deterministic and side-effect free so this can
    be used both in tests and command layers.
    """
    if backlog_threshold < 0:
        raise ValueError("backlog_threshold must be >= 0")

    counts_raw = summary.get("counts_by_type")
    if not isinstance(counts_raw, Mapping):
        raise ValueError("summary.counts_by_type must be a mapping")
    counts_by_type = {str(k): int(v) for k, v in counts_raw.items()}

    duration_ms_raw = summary.get("duration_ms", 0)
    if not isinstance(duration_ms_raw, int | float):
        raise ValueError("summary.duration_ms must be numeric")
    duration_ms = float(duration_ms_raw)
    if duration_ms < 0:
        raise ValueError("summary.duration_ms must be >= 0")

    total_events_raw = summary.get("total_events", 0)
    if not isinstance(total_events_raw, int):
        raise ValueError("summary.total_events must be an int")
    if total_events_raw < 0:
        raise ValueError("summary.total_events must be >= 0")

    planned = counts_by_type.get("ActionPlanned", 0)
    executed = (
        counts_by_type.get("ActionExecuted", 0)
        + counts_by_type.get("ActionExecutionFailed", 0)
    )
    reconcile_backlog = max(0, planned - executed)

    recent_reconcile_failures = (
        counts_by_type.get("ActionExecutionFailed", 0)
        + counts_by_type.get("RecoveryTriggered", 0)
    )

    opened_gates = counts_by_type.get("HumanGateOpened", 0)
    resolved_gates = counts_by_type.get("HumanGateResolved", 0)
    pending_gate_count = max(0, opened_gates - resolved_gates)

    has_stale_gates = pending_gate_count > 0 and duration_ms >= 300_000.0

    return {
        "reconcile_backlog": reconcile_backlog,
        "reconcile_backlog_threshold": backlog_threshold,
        "recent_reconcile_failures": recent_reconcile_failures,
        "pending_gate_count": pending_gate_count,
        "has_stale_gates": has_stale_gates,
        "source_total_events": total_events_raw,
        "source_duration_ms": duration_ms,
    }

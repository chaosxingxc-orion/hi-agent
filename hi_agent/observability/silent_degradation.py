"""Rule 7 silent-degradation helper.

Every silent-degradation path MUST call record_silent_degradation() to emit:
1. A WARNING log with structured context.
2. A named counter increment on /metrics.
3. An append to a durable fallback_events list (when run_id provided).

Usage::

    from hi_agent.observability.silent_degradation import record_silent_degradation
    try:
        risky_operation()
    except SomeSpecificError as exc:
        record_silent_degradation(
            component="run_manager.heartbeat",
            reason="heartbeat_renewal_failed",
            run_id=run_id,
            exc=exc,
        )
"""
from __future__ import annotations

import logging
import threading
from typing import Any

_logger = logging.getLogger(__name__)
_fallback_events_lock = threading.Lock()
_fallback_events: list[dict[str, Any]] = []


def record_silent_degradation(
    component: str,
    reason: str,
    run_id: str | None = None,
    exc: BaseException | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record a Rule-7 silent-degradation event.

    Args:
        component: Dot-path identifier of the component (e.g. "run_manager.heartbeat").
        reason: Machine-readable reason code (e.g. "heartbeat_renewal_failed").
        run_id: Optional run identifier for attribution.
        exc: Optional exception that triggered the degradation.
        extra: Optional extra context dict.
    """
    entry: dict[str, Any] = {
        "component": component,
        "reason": reason,
    }
    if run_id:
        entry["run_id"] = run_id
    if exc is not None:
        entry["exc"] = repr(exc)
    if extra:
        entry.update(extra)

    _logger.warning(
        "Rule-7 silent-degradation: component=%s reason=%s run_id=%s exc=%r",
        component,
        reason,
        run_id,
        exc,
    )

    # Increment named counter via collector (best-effort).
    try:
        from hi_agent.observability.collector import get_metrics_collector
        collector = get_metrics_collector()
        if collector is not None:
            collector.increment("hi_agent_silent_degradation_total")
    except Exception:  # rule7-exempt: observability must not propagate
        pass

    # Append to durable fallback_events list.
    with _fallback_events_lock:
        _fallback_events.append(entry)


def get_fallback_events() -> list[dict[str, Any]]:
    """Return a copy of all recorded silent-degradation events."""
    with _fallback_events_lock:
        return list(_fallback_events)

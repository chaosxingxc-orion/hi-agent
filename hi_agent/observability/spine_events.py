"""Typed spine event emitters for the 14 observability spine layers.

Each emitter is intentionally thin: increment a named counter, emit a
structured log at DEBUG.  Callers supply the tenant_id (and optionally
profile_id or tool_name) for label attribution; no high-cardinality labels
(run_id / task_id are intentionally excluded from counter labels).

Spine layers covered here (AX-A4 additions):
  - llm_call            — dispatched by HttpLLMGateway.complete,
                          HTTPGateway.complete, HTTPStreamingGateway.stream
  - tool_call           — dispatched by ActionDispatcher._execute_action_with_retry
  - heartbeat_renewed   — dispatched by RunManager._heartbeat_loop on renewal
  - trace_id_propagated — dispatched by TraceIdMiddleware per HTTP request
"""
from __future__ import annotations

import contextlib
import logging

from hi_agent.observability.metric_counter import Counter

_logger = logging.getLogger(__name__)

# Module-level counter proxies — constructed once; .labels() is called per
# emit to bind the per-call label values without allocating a new registry entry.
_llm_call_counter = Counter("hi_agent_spine_llm_call_total")
_tool_call_counter = Counter("hi_agent_spine_tool_call_total")
_heartbeat_counter = Counter("hi_agent_spine_heartbeat_renewed_total")
_trace_id_counter = Counter("hi_agent_spine_trace_id_propagated_total")


def emit_llm_call(*, tenant_id: str = "", profile_id: str = "") -> None:
    """Emit when an LLM completion request is dispatched.

    Call this once per outgoing LLM request, before the actual HTTP send.
    Only the ``profile`` label is attached to keep cardinality bounded.

    Args:
        tenant_id: Tenant identifier for log attribution (not a counter label).
        profile_id: Profile/tier for counter label attribution.
    """
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501
        _llm_call_counter.labels(profile=profile_id or "unknown").inc()
    _logger.debug("spine.llm_call", extra={"tenant_id": tenant_id})


def emit_tool_call(
    *, tool_name: str = "", tenant_id: str = "", profile_id: str = ""
) -> None:
    """Emit when a tool execution is dispatched (first attempt boundary).

    Args:
        tool_name: Name of the capability / tool being invoked.
        tenant_id: Tenant identifier for log attribution (not a counter label).
        profile_id: Profile/tier for counter label attribution.
    """
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501
        _tool_call_counter.labels(
            tool=tool_name or "unknown",
            profile=profile_id or "unknown",
        ).inc()
    _logger.debug("spine.tool_call tool=%s", tool_name, extra={"tenant_id": tenant_id})


def emit_heartbeat_renewed(*, tenant_id: str = "", run_id: str = "") -> None:
    """Emit when a run lease heartbeat is successfully renewed.

    The ``run_id`` is intentionally excluded from counter labels to avoid
    high-cardinality explosion; it is included only in the DEBUG log.

    Args:
        tenant_id: Tenant identifier for log attribution.
        run_id: Run identifier for log attribution (not a counter label).
    """
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501
        _heartbeat_counter.labels().inc()
    _logger.debug(
        "spine.heartbeat_renewed run=%s",
        run_id[:8] if run_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_trace_id_propagated(*, trace_id: str = "", tenant_id: str = "") -> None:
    """Emit when a trace_id is successfully propagated through HTTP middleware.

    The full ``trace_id`` is excluded from counter labels; only a truncated
    prefix appears in the DEBUG log.

    Args:
        trace_id: The trace_id that was extracted or minted.
        tenant_id: Tenant identifier for log attribution (not a counter label).
    """
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501
        _trace_id_counter.labels().inc()
    _logger.debug(
        "spine.trace_id_propagated trace=%s",
        trace_id[:8] if trace_id else "none",
        extra={"tenant_id": tenant_id},
    )


__all__ = [
    "emit_heartbeat_renewed",
    "emit_llm_call",
    "emit_tool_call",
    "emit_trace_id_propagated",
]

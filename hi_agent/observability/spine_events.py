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

Spine layers added (w25-F): run_manager, tenant_context, reasoning_loop,
  capability_handler, sync_bridge, http_transport, artifact_ledger, event_store

Directive telemetry (M.5 additions):
  - stage_skipped       — dispatched by run_linear/run_graph directive handler (skip)
  - stage_inserted      — dispatched by run_linear/run_resume directive handler (insert)
  - stage_replanned     — dispatched by run_linear/run_graph/run_resume directive handler
                          (skip_to, repeat)
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
_stage_skipped_counter = Counter("hi_agent_spine_stage_skipped_total")
_stage_inserted_counter = Counter("hi_agent_spine_stage_inserted_total")
_stage_replanned_counter = Counter("hi_agent_spine_stage_replanned_total")

# w25-F: counters for 8 previously unwired layers
_run_manager_counter = Counter("hi_agent_spine_run_manager_total")
_tenant_context_counter = Counter("hi_agent_spine_tenant_context_total")
_reasoning_loop_counter = Counter("hi_agent_spine_reasoning_loop_total")
_capability_handler_counter = Counter("hi_agent_spine_capability_handler_total")
_sync_bridge_counter = Counter("hi_agent_spine_sync_bridge_total")
_http_transport_counter = Counter("hi_agent_spine_http_transport_total")
_artifact_ledger_counter = Counter("hi_agent_spine_artifact_ledger_total")
_event_store_counter = Counter("hi_agent_spine_event_store_total")


def emit_llm_call(*, tenant_id: str = "", profile_id: str = "") -> None:
    """Emit when an LLM completion request is dispatched.

    Call this once per outgoing LLM request, before the actual HTTP send.
    Only the ``profile`` label is attached to keep cardinality bounded.

    Args:
        tenant_id: Tenant identifier for log attribution (not a counter label).
        profile_id: Profile/tier for counter label attribution.
    """
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
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
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
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
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
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
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _trace_id_counter.labels().inc()
    _logger.debug(
        "spine.trace_id_propagated trace=%s",
        trace_id[:8] if trace_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_run_manager(*, tenant_id: str = "", run_id: str = "") -> None:
    """Emit when a run is enqueued by RunManager (run_queued lifecycle boundary)."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _run_manager_counter.labels().inc()
    _logger.debug(
        "spine.run_manager run=%s",
        run_id[:8] if run_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_tenant_context(*, tenant_id: str = "") -> None:
    """Emit when per-request tenant context is resolved (middleware boundary)."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _tenant_context_counter.labels().inc()
    _logger.debug("spine.tenant_context", extra={"tenant_id": tenant_id})


def emit_reasoning_loop(*, tenant_id: str = "", run_id: str = "") -> None:
    """Emit at the entry of each reasoning-loop stage (lease_acquired boundary)."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _reasoning_loop_counter.labels().inc()
    _logger.debug(
        "spine.reasoning_loop run=%s",
        run_id[:8] if run_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_capability_handler(
    *, tool_name: str = "", tenant_id: str = "", run_id: str = ""
) -> None:
    """Emit when a capability handler is dispatched (heartbeat-renewal boundary)."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _capability_handler_counter.labels(tool=tool_name or "unknown").inc()
    _logger.debug(
        "spine.capability_handler tool=%s run=%s",
        tool_name,
        run_id[:8] if run_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_sync_bridge(*, tenant_id: str = "") -> None:
    """Emit when the sync→async bridge dispatches a coroutine."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _sync_bridge_counter.labels().inc()
    _logger.debug("spine.sync_bridge", extra={"tenant_id": tenant_id})


def emit_http_transport(*, tenant_id: str = "", profile_id: str = "") -> None:
    """Emit when an outbound HTTP request is sent by the LLM transport layer."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _http_transport_counter.labels(profile=profile_id or "unknown").inc()
    _logger.debug("spine.http_transport", extra={"tenant_id": tenant_id})


def emit_artifact_ledger(*, tenant_id: str = "", run_id: str = "") -> None:
    """Emit when an artifact is registered in the ArtifactLedger."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _artifact_ledger_counter.labels().inc()
    _logger.debug(
        "spine.artifact_ledger run=%s",
        run_id[:8] if run_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_event_store(*, tenant_id: str = "", run_id: str = "") -> None:
    """Emit when an event is successfully persisted to the EventStore."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _event_store_counter.labels().inc()
    _logger.debug(
        "spine.event_store run=%s",
        run_id[:8] if run_id else "none",
        extra={"tenant_id": tenant_id},
    )


def emit_stage_skipped(
    run_id: str,
    stage_id: str,
    target_stage_id: str | None,
    posture: str = "dev",
    reason: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Emit when a stage is removed from the run plan via a skip directive."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _stage_skipped_counter.labels(posture=posture or "unknown").inc()
    _logger.debug(
        "spine.stage_skipped run=%s stage=%s target=%s reason=%s",
        run_id[:8] if run_id else "none",
        stage_id,
        target_stage_id,
        reason,
        extra={"correlation_id": correlation_id},
    )


def emit_stage_inserted(
    run_id: str,
    anchor_stage_id: str | None,
    new_stage_id: str,
    posture: str = "dev",
    reason: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Emit when a new stage is inserted into the run plan via an insert directive."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _stage_inserted_counter.labels(posture=posture or "unknown").inc()
    _logger.debug(
        "spine.stage_inserted run=%s anchor=%s new=%s reason=%s",
        run_id[:8] if run_id else "none",
        anchor_stage_id,
        new_stage_id,
        reason,
        extra={"correlation_id": correlation_id},
    )


def emit_stage_replanned(
    run_id: str,
    action: str,
    from_stage: str | None,
    to_stage: str | None,
    posture: str = "dev",
    reason: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Emit when a skip_to or repeat directive changes the stage traversal plan."""
    with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 27
        _stage_replanned_counter.labels(
            action=action or "unknown", posture=posture or "unknown"
        ).inc()
    _logger.debug(
        "spine.stage_replanned run=%s action=%s from=%s to=%s reason=%s",
        run_id[:8] if run_id else "none",
        action,
        from_stage,
        to_stage,
        reason,
        extra={"correlation_id": correlation_id},
    )


__all__ = [
    "emit_artifact_ledger",
    "emit_capability_handler",
    "emit_event_store",
    "emit_heartbeat_renewed",
    "emit_http_transport",
    "emit_llm_call",
    "emit_reasoning_loop",
    "emit_run_manager",
    "emit_stage_inserted",
    "emit_stage_replanned",
    "emit_stage_skipped",
    "emit_sync_bridge",
    "emit_tenant_context",
    "emit_tool_call",
    "emit_trace_id_propagated",
]

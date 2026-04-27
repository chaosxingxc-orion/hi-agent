"""Audit event emitter for hi-agent (HI-W1-D2-001).

Appends structured audit events to .hi_agent/audit/events.jsonl so that
explicit policy decisions (e.g. evolve enabled in prod) are observable
without requiring a full observability stack.

W10-005: extended with capability.invoke, capability.deny, mcp.tools_call,
and mcp.server_restart event helpers.

P1-2d: ToolCallAuditEvent dataclass + AuditStore with record_tool_call().
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# P1-2d: structured audit dataclass + store
# ---------------------------------------------------------------------------


@dataclass
class ToolCallAuditEvent:
    """Structured audit record for a single tool invocation decision."""

    event_id: str  # uuid4 hex
    session_id: str
    run_id: str  # empty string if not in a run
    principal: str
    tool_name: str
    risk_class: str  # from CapabilityDescriptor, or "unknown"
    source: str  # "runner" | "http_tools" | "http_mcp" | "cli"
    argument_digest: str  # sha256[:16] of redacted args JSON
    decision: Literal["allow", "deny", "approval_required"]
    denial_reason: str | None
    approval_id: str | None
    result_status: Literal["ok", "error", "timeout"] | None
    duration_ms: float | None
    timestamp: str  # ISO8601


class AuditStore:
    """Persistent audit store for tool-call governance events (P1-2d).

    Appends ToolCallAuditEvent records to the same JSONL file used by emit().
    All exceptions are swallowed so audit never blocks execution.
    """

    def record_tool_call(
        self,
        *,
        capability_name: str,
        principal: str,
        session_id: str,
        source: str,
        decision: str,
        reason: str | None,
        argument_digest: str,
        run_id: str = "",
        risk_class: str = "unknown",
        result_status: str | None = None,
        duration_ms: float | None = None,
        approval_id: str | None = None,
    ) -> None:
        """Create a ToolCallAuditEvent and persist it."""
        now = datetime.now(UTC).isoformat()
        event = ToolCallAuditEvent(
            event_id=uuid.uuid4().hex,
            session_id=session_id,
            run_id=run_id,
            principal=principal,
            tool_name=capability_name,
            risk_class=risk_class,
            source=source,
            argument_digest=argument_digest,
            decision=decision,  # type: ignore[arg-type]
            denial_reason=reason if decision != "allow" else None,
            approval_id=approval_id,
            result_status=result_status,  # type: ignore[arg-type]
            duration_ms=duration_ms,
            timestamp=now,
        )
        # Audit emitters must never block execution.
        with contextlib.suppress(Exception):  # rule7-exempt: audit emitters must not block execution path
            emit(
                "tool_call.audit",
                {
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "run_id": event.run_id,
                    "principal": event.principal,
                    "tool_name": event.tool_name,
                    "risk_class": event.risk_class,
                    "source": event.source,
                    "argument_digest": event.argument_digest,
                    "decision": event.decision,
                    "denial_reason": event.denial_reason,
                    "approval_id": event.approval_id,
                    "result_status": event.result_status,
                    "duration_ms": event.duration_ms,
                    "timestamp": event.timestamp,
                },
            )


def emit(event_name: str, payload: dict) -> None:
    """Append an audit event to .hi_agent/audit/events.jsonl.

    Args:
        event_name: Short identifier for the event type, e.g.
            "evolve.explicit_on_in_prod".
        payload: Arbitrary key-value metadata to include in the event record.
    """
    audit_dir = Path(".hi_agent/audit")
    audit_dir.mkdir(parents=True, exist_ok=True)
    event = {"event": event_name, "timestamp": time.time(), **payload}
    with open(audit_dir / "events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# W10-005: typed helpers for M4 audit trail
# ---------------------------------------------------------------------------


def emit_capability_invoke(
    capability_name: str,
    role: str | None,
    duration_ms: int,
    *,
    truncated: bool = False,
) -> None:
    """Record a successful capability invocation."""
    emit(
        "capability.invoke",
        {
            "capability_name": capability_name,
            "role": role,
            "duration_ms": duration_ms,
            "output_truncated": truncated,
        },
    )


def emit_capability_deny(
    capability_name: str,
    role: str | None,
    reason: str,
) -> None:
    """Record a denied capability invocation (RBAC or availability check)."""
    emit(
        "capability.deny",
        {
            "capability_name": capability_name,
            "role": role,
            "reason": reason,
        },
    )


def emit_mcp_tools_call(
    server_id: str,
    tool_name: str,
    duration_ms: int,
    *,
    error: str | None = None,
) -> None:
    """Record an MCP tools/call invocation."""
    emit(
        "mcp.tools_call",
        {
            "server_id": server_id,
            "tool_name": tool_name,
            "duration_ms": duration_ms,
            "error": error,
        },
    )


def emit_mcp_server_restart(
    server_id: str,
    attempt: int,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    """Record an MCP server restart attempt."""
    emit(
        "mcp.server_restart",
        {
            "server_id": server_id,
            "attempt": attempt,
            "success": success,
            "error": error,
        },
    )

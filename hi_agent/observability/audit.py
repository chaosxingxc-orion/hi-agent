"""Audit event emitter for hi-agent (HI-W1-D2-001).

Appends structured audit events to .hi_agent/audit/events.jsonl so that
explicit policy decisions (e.g. evolve enabled in prod) are observable
without requiring a full observability stack.

W10-005: extended with capability.invoke, capability.deny, mcp.tools_call,
and mcp.server_restart event helpers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


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

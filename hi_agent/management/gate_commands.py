"""Command-style helpers around human gate APIs."""

from __future__ import annotations

from hi_agent.auth.rbac_enforcer import RBACEnforcer
from hi_agent.auth.soc_guard import enforce_submitter_approver_separation
from hi_agent.management.gate_api import GateRecord, InMemoryGateAPI, resolve_gate_api


def cmd_gate_list(api: InMemoryGateAPI) -> dict[str, object]:
    """Return pending gate rows in command response shape."""
    pending_rows: list[dict[str, object]] = []
    for record in api.list_pending():
        pending_rows.append(
            {
                "gate_ref": record.context.gate_ref,
                "run_id": record.context.run_id,
                "stage_id": record.context.stage_id,
                "submitter": record.context.submitter,
                "status": record.status.value,
                "opened_at": record.context.opened_at,
            }
        )
    return {"command": "gate_list", "pending_count": len(pending_rows), "pending": pending_rows}


def cmd_gate_status(api: InMemoryGateAPI, *, gate_ref: str) -> dict[str, object]:
    """Return one gate status in command response shape."""
    normalized_gate_ref = gate_ref.strip()
    if not normalized_gate_ref:
        raise ValueError("gate_ref must be a non-empty string")
    record = api.get_gate(normalized_gate_ref)
    return {
        "command": "gate_status",
        "gate_ref": record.context.gate_ref,
        "status": record.status.value,
        "resolution_by": record.resolution_by,
        "resolution_reason": record.resolution_reason,
    }


def cmd_gate_resolve(
    api: InMemoryGateAPI,
    *,
    gate_ref: str,
    action: str,
    approver: str,
    comment: str | None = None,
    reason: str | None = None,
    rbac: RBACEnforcer | None = None,
    approver_role: str | None = None,
    soc_enabled: bool = True,
) -> dict[str, object]:
    """Resolve a gate with optional RBAC and SoC checks."""
    if not isinstance(approver, str):
        raise TypeError("approver must be a string")
    if rbac is not None:
        rbac.enforce(
            role=(approver_role or "").strip(),
            operation="management.gate.resolve",
        )
    if action.strip().lower() == "approve" and soc_enabled:
        record = api.get_gate(gate_ref)
        enforce_submitter_approver_separation(
            submitter=record.context.submitter,
            approver=approver,
            enabled=True,
        )
    resolved = resolve_gate_api(
        api=api,
        gate_ref=gate_ref,
        action=action,
        approver=approver,
        comment=comment,
        reason=reason,
    )
    return _record_to_resolve_response(resolved)


def cmd_gate_operational_signal(
    api: InMemoryGateAPI,
    *,
    now_seconds: float,
    stale_gate_threshold_seconds: float,
) -> dict[str, object]:
    """Build gate operational readiness signal."""
    pending = api.list_pending()
    oldest_age: float | None = None
    for record in pending:
        age = max(0.0, now_seconds - float(record.context.opened_at))
        oldest_age = age if oldest_age is None else max(oldest_age, age)
    has_stale = (
        oldest_age is not None
        and stale_gate_threshold_seconds > 0
        and oldest_age >= stale_gate_threshold_seconds
    )
    return {
        "pending_gate_count": len(pending),
        "oldest_pending_gate_age_seconds": oldest_age,
        "stale_gate_threshold_seconds": stale_gate_threshold_seconds,
        "has_stale_gates": has_stale,
    }


def cmd_gate_list_pending(api: InMemoryGateAPI) -> list[dict[str, object]]:
    """Backward-compatible list helper returning rows only."""
    response = cmd_gate_list(api)
    return list(response["pending"])


def _record_to_resolve_response(record: GateRecord) -> dict[str, object]:
    """Convert GateRecord to command response payload."""
    return {
        "command": "gate_resolve",
        "gate_ref": record.context.gate_ref,
        "status": record.status.value,
        "resolved_at": record.resolved_at,
        "resolution_by": record.resolution_by,
        "resolution_reason": record.resolution_reason,
    }

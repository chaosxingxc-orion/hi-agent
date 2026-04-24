"""In-memory Human Gate API surface used by management workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from time import time

from hi_agent.management.gate_context import GateContext
from hi_agent.management.gate_timeout import GateTimeoutPolicy, resolve_gate_timeout


class GateAction(StrEnum):
    """User-facing resolution actions."""

    APPROVE = "approve"
    REJECT = "reject"
    BACKTRACK = "backtrack"
    REMEDIATE = "remediate"


class GateStatus(StrEnum):
    """Lifecycle status of a gate."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    BACKTRACKED = "backtracked"
    REMEDIATED = "remediated"


@dataclass(frozen=True)
class GateRecord:
    """Stored gate state snapshot."""

    context: GateContext
    status: GateStatus
    timeout_seconds: float
    timeout_policy: GateTimeoutPolicy
    resolution_by: str | None = None
    resolution_comment: str | None = None
    resolution_reason: str | None = None
    resolved_at: float | None = None
    escalation_target: str | None = None
    project_id: str = ""


class InMemoryGateAPI:
    """Simple in-memory gate manager for MVP and tests.

    This intentionally keeps state local and deterministic. In production this
    service can be replaced by a durable backend while preserving method
    contracts.
    """

    def __init__(
        self,
        *,
        enforce_separation_of_concerns: bool = True,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        """Initialize empty in-memory gate state with optional policy hooks."""
        self._records: dict[str, GateRecord] = {}
        self._enforce_soc = enforce_separation_of_concerns
        self._now_fn = now_fn or time

    def create_gate(
        self,
        *,
        context: GateContext,
        timeout_seconds: float = 300.0,
        timeout_policy: GateTimeoutPolicy = GateTimeoutPolicy.REJECT,
        escalation_target: str | None = None,
    ) -> GateRecord:
        """Create a new pending gate."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if context.gate_ref in self._records:
            raise ValueError(f"gate {context.gate_ref} already exists")

        record = GateRecord(
            context=context,
            status=GateStatus.PENDING,
            timeout_seconds=timeout_seconds,
            timeout_policy=timeout_policy,
            escalation_target=escalation_target.strip() if escalation_target else None,
        )
        self._records[context.gate_ref] = record
        return record

    def list_pending(self) -> list[GateRecord]:
        """List pending gates sorted by open time then gate ref."""
        rows = [record for record in self._records.values() if record.status is GateStatus.PENDING]
        return sorted(rows, key=lambda record: (record.context.opened_at, record.context.gate_ref))

    def get_gate(self, gate_ref: str) -> GateRecord:
        """Fetch a gate by reference."""
        normalized_gate_ref = gate_ref.strip()
        if not normalized_gate_ref:
            raise ValueError("gate_ref must be a non-empty string")
        record = self._records.get(normalized_gate_ref)
        if record is None:
            raise ValueError(f"gate {normalized_gate_ref} not found")
        return record

    def resolve(
        self,
        *,
        gate_ref: str,
        action: str,
        approver: str,
        comment: str | None = None,
        reason: str | None = None,
    ) -> GateRecord:
        """Resolve a pending gate with approve/reject action."""
        normalized_approver = approver.strip()
        if not normalized_approver:
            raise ValueError("approver must be a non-empty string")
        normalized_action = action.strip().lower()
        _valid_actions = {
            GateAction.APPROVE.value,
            GateAction.REJECT.value,
            GateAction.BACKTRACK.value,
            GateAction.REMEDIATE.value,
        }
        if normalized_action not in _valid_actions:
            raise ValueError(f"action must be one of {sorted(_valid_actions)}")

        record = self.get_gate(gate_ref)
        if record.status is not GateStatus.PENDING:
            msg = f"gate {record.context.gate_ref} already resolved as {record.status.value}"
            raise ValueError(msg)

        if (
            self._enforce_soc
            and normalized_action == GateAction.APPROVE.value
            and normalized_approver == record.context.submitter
        ):
            raise PermissionError("submitter cannot approve gate when SoC is enforced")

        target_status = {
            GateAction.APPROVE.value: GateStatus.APPROVED,
            GateAction.REJECT.value: GateStatus.REJECTED,
            GateAction.BACKTRACK.value: GateStatus.BACKTRACKED,
            GateAction.REMEDIATE.value: GateStatus.REMEDIATED,
        }.get(normalized_action, GateStatus.REJECTED)
        resolved = replace(
            record,
            status=target_status,
            resolution_by=normalized_approver,
            resolution_comment=comment.strip() if comment and comment.strip() else None,
            resolution_reason=reason.strip() if reason and reason.strip() else None,
            resolved_at=float(self._now_fn()),
        )
        self._records[record.context.gate_ref] = resolved
        return resolved

    def apply_timeouts(self) -> list[GateRecord]:
        """Apply timeout policy to pending gates and return changed records."""
        changed: list[GateRecord] = []
        for gate_ref in [record.context.gate_ref for record in self.list_pending()]:
            record = self._records[gate_ref]
            timeout_result = resolve_gate_timeout(
                opened_at=record.context.opened_at,
                timeout_seconds=record.timeout_seconds,
                policy=record.timeout_policy,
                now_fn=self._now_fn,
                escalation_target=record.escalation_target,
            )
            if not timeout_result.timed_out:
                continue

            if timeout_result.action == "approve":
                updated = replace(
                    record,
                    status=GateStatus.APPROVED,
                    resolution_by="system:timeout",
                    resolution_reason=timeout_result.reason,
                    resolved_at=timeout_result.resolved_at,
                )
            elif timeout_result.action == "reject":
                updated = replace(
                    record,
                    status=GateStatus.REJECTED,
                    resolution_by="system:timeout",
                    resolution_reason=timeout_result.reason,
                    resolved_at=timeout_result.resolved_at,
                )
            else:
                updated = replace(
                    record,
                    status=GateStatus.ESCALATED,
                    resolution_by="system:timeout",
                    resolution_reason=timeout_result.reason,
                    resolved_at=timeout_result.resolved_at,
                    escalation_target=timeout_result.escalation_target,
                )
            self._records[gate_ref] = updated
            changed.append(updated)
        return changed


def resolve_gate_api(
    *,
    api: InMemoryGateAPI,
    gate_ref: str,
    action: str,
    approver: str,
    comment: str | None = None,
    reason: str | None = None,
) -> GateRecord:
    """Small command-style wrapper to resolve a gate."""
    return api.resolve(
        gate_ref=gate_ref,
        action=action,
        approver=approver,
        comment=comment,
        reason=reason,
    )

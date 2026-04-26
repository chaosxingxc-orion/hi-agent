"""Human-gate context model and builder helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(frozen=True)
class GateContext:
    """Immutable context attached to a human approval gate.

    The context captures enough metadata for approvers to make a decision
    without querying additional runtime state in MVP mode.
    """

    gate_ref: str
    run_id: str
    stage_id: str
    branch_id: str
    submitter: str
    decision_ref: str | None = None
    rationale: str | None = None
    opened_at: float = field(default_factory=time)
    metadata: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""


def build_gate_context(
    *,
    gate_ref: str,
    run_id: str,
    stage_id: str,
    branch_id: str,
    submitter: str,
    decision_ref: str | None = None,
    rationale: str | None = None,
    metadata: dict[str, Any] | None = None,
    now_fn: Callable[[], float] | None = None,
) -> GateContext:
    """Build and validate a :class:`GateContext`.

    Args:
      gate_ref: Unique gate reference.
      run_id: Parent run identifier.
      stage_id: Stage where gate was opened.
      branch_id: Branch tied to the decision.
      submitter: Actor who requested the gate.
      decision_ref: Optional decision artifact reference.
      rationale: Optional human-facing reason.
      metadata: Optional additional context.
      now_fn: Optional injected clock for deterministic tests.
    """
    required = {
        "gate_ref": gate_ref,
        "run_id": run_id,
        "stage_id": stage_id,
        "branch_id": branch_id,
        "submitter": submitter,
    }
    for field_name, value in required.items():
        if not value or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    clock = now_fn or time
    opened_at = float(clock())
    if opened_at < 0:
        raise ValueError("opened_at must be non-negative")

    return GateContext(
        gate_ref=gate_ref.strip(),
        run_id=run_id.strip(),
        stage_id=stage_id.strip(),
        branch_id=branch_id.strip(),
        submitter=submitter.strip(),
        decision_ref=decision_ref.strip() if decision_ref and decision_ref.strip() else None,
        rationale=rationale.strip() if rationale and rationale.strip() else None,
        opened_at=opened_at,
        metadata=dict(metadata or {}),
    )

"""Request and response dataclasses for runtime adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts.branch import BranchState
from hi_agent.contracts.run import RunState


@dataclass(frozen=True)
class StartRunRequest:
    """Request to start a new run."""

    task_contract: dict[str, Any]
    task_family: str = "quick_task"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StartRunResponse:
    """Response from starting a run."""

    run_id: str
    status: RunState = RunState.CREATED


@dataclass(frozen=True)
class SignalRunRequest:
    """Request to push an external signal to a run."""

    run_id: str
    signal_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryRunResponse:
    """Snapshot of run lifecycle state."""

    run_id: str
    state: RunState
    current_stage: str | None = None
    active_branches: list[str] = field(default_factory=list)
    events_count: int = 0


@dataclass(frozen=True)
class TraceRuntimeView:
    """Diagnostic runtime snapshot for a run."""

    run_id: str
    stage_graph_snapshot: dict[str, Any] = field(default_factory=dict)
    trajectory_snapshot: dict[str, Any] = field(default_factory=dict)
    memory_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenBranchRequest:
    """Request to open a new branch in a stage."""

    run_id: str
    stage_id: str
    branch_id: str
    rationale: str = ""


@dataclass(frozen=True)
class BranchStateUpdateRequest:
    """Request to update a branch lifecycle state."""

    run_id: str
    branch_id: str
    target_state: BranchState
    failure_code: str | None = None


@dataclass(frozen=True)
class HumanGateRequest:
    """Request to open a human gate for approval."""

    run_id: str
    gate_type: str
    gate_ref: str
    context: dict[str, Any] = field(default_factory=dict)
    timeout_s: int = 3600


@dataclass(frozen=True)
class ApprovalRequest:
    """Human approval or rejection of a gate."""

    gate_ref: str
    decision: str  # "approved" or "rejected"
    reviewer_id: str = ""
    comment: str = ""


@dataclass(frozen=True)
class KernelManifest:
    """Runtime capabilities and metadata."""

    version: str = "0.1.0"
    supported_substrates: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

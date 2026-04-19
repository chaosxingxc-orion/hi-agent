"""Request and response dataclasses for runtime adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts.branch import BranchState
from hi_agent.contracts.execution_provenance import ExecutionProvenance
from hi_agent.contracts.run import RunState


@dataclass(frozen=True)
class StartRunRequest:
    """Request to start a new run."""

    task_contract: dict[str, Any]
    task_family: str = "quick_task"
    config: dict[str, Any] = field(default_factory=dict)
    profile_id: str | None = None


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
    run_id: str = ""
    reviewer_id: str = ""
    comment: str = ""


@dataclass(frozen=True)
class KernelManifest:
    """Runtime capabilities and metadata."""

    version: str = "0.1.0"
    supported_substrates: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """Structured result of a completed run — consumable by downstream callers.

    Replaces the bare ``"completed"`` / ``"failed"`` status string. The
    ``__str__`` implementation returns ``status`` so existing code that
    compares ``result == "completed"`` continues to work.
    """

    run_id: str
    status: str  # "completed" | "failed"
    stages: list[dict[str, Any]] = field(default_factory=list)
    """Per-stage summary: stage_id, outcome, findings, decisions, artifact_ids."""
    artifacts: list[str] = field(default_factory=list)
    """All artifact IDs collected across all stages."""
    error: str | None = None
    """Failure reason when status == "failed". Contains exception message or cause."""
    duration_ms: int = 0
    # Failure attribution — populated only when status == "failed"
    failure_code: str | None = None
    """Standard failure code (matches TRACE FailureCode taxonomy)."""
    failed_stage_id: str | None = None
    """ID of the stage that caused the run to fail."""
    is_retryable: bool = False
    """Whether the failure is transient and the run can be safely retried."""
    execution_provenance: ExecutionProvenance | None = None
    """Structured provenance for machine-readable run classification (HI-W1-D3-001)."""

    @property
    def success(self) -> bool:
        """Backward-compatible success flag used by async/integration callers."""
        return self.status == "completed"

    def __str__(self) -> str:  # noqa: D105
        return self.status

    def __eq__(self, other: object) -> bool:  # noqa: D105
        if isinstance(other, str):
            return self.status == other
        if isinstance(other, RunResult):
            return self.status == other.status and self.run_id == other.run_id
        return NotImplemented

    def __hash__(self) -> int:  # noqa: D105
        # Hash matches the status string so `result in {"completed", "failed"}` works.
        return hash(self.status)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "stages": self.stages,
            "artifacts": self.artifacts,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "failure_code": self.failure_code,
            "failed_stage_id": self.failed_stage_id,
            "is_retryable": self.is_retryable,
            "execution_provenance": self.execution_provenance.to_dict() if self.execution_provenance else None,
        }

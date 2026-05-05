"""Request and response dataclasses for runtime adapter protocol."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts.branch import BranchState
from hi_agent.contracts.execution_provenance import ExecutionProvenance
from hi_agent.contracts.run import RunState

_logger = logging.getLogger(__name__)


def _validate_spine(obj_name: str, fields: dict[str, str]) -> None:
    """Posture-aware spine validator (Rule 11, Rule 12).

    W35-T1: Asserts every required spine field is non-empty.

    Under research/prod posture: raises ``SpineCompletenessError`` listing
    every missing field. Under dev posture: logs a warning so local tooling
    keeps working while making the gap visible.

    Args:
        obj_name: Class name used in error/log messages.
        fields: Mapping of field name to its current value. Empty values
            (empty strings or ``None``) are reported as missing.
    """
    from hi_agent.contracts.reasoning import SpineCompletenessError

    missing = [name for name, value in fields.items() if not value]
    if not missing:
        return
    from hi_agent.config.posture import Posture

    posture = Posture.from_env()
    if posture.is_strict:
        raise SpineCompletenessError(
            f"{obj_name} constructed without required spine fields "
            f"under posture={posture.value}: missing={missing}. "
            "Populate at the construction site (Rule 12)."
        )
    _logger.warning(
        "%s constructed with empty spine fields missing=%s posture=%s; "
        "would fail-closed under research/prod posture (Rule 12).",
        obj_name,
        missing,
        posture.value,
    )


def _validate_tenant_id(obj_name: str, tenant_id: str) -> None:
    """Backward-compatible single-field validator.

    Retained for callers that only need to validate ``tenant_id``. Internally
    delegates to :func:`_validate_spine`.
    """
    _validate_spine(obj_name, {"tenant_id": tenant_id})


@dataclass(frozen=True)
class StartRunRequest:
    """Request to start a new run."""

    task_contract: dict[str, Any]
    task_family: str = "quick_task"
    config: dict[str, Any] = field(default_factory=dict)
    profile_id: str | None = None
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        # Spine: tenant_id required (run_id is not yet known at start time).
        _validate_spine("StartRunRequest", {"tenant_id": self.tenant_id})


@dataclass(frozen=True)
class StartRunResponse:
    """Response from starting a run."""

    run_id: str
    status: RunState = RunState.CREATED
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        _validate_spine(
            "StartRunResponse",
            {"tenant_id": self.tenant_id, "run_id": self.run_id},
        )


@dataclass(frozen=True)
class SignalRunRequest:
    """Request to push an external signal to a run."""

    run_id: str
    signal_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        _validate_spine(
            "SignalRunRequest",
            {"tenant_id": self.tenant_id, "run_id": self.run_id},
        )


@dataclass(frozen=True)
class QueryRunResponse:
    """Snapshot of run lifecycle state."""

    run_id: str
    state: RunState
    current_stage: str | None = None
    active_branches: list[str] = field(default_factory=list)
    events_count: int = 0
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        _validate_spine(
            "QueryRunResponse",
            {"tenant_id": self.tenant_id, "run_id": self.run_id},
        )


@dataclass(frozen=True)
class TraceRuntimeView:
    """Diagnostic runtime snapshot for a run."""

    run_id: str
    stage_graph_snapshot: dict[str, Any] = field(default_factory=dict)
    trajectory_snapshot: dict[str, Any] = field(default_factory=dict)
    memory_summary: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        _validate_spine(
            "TraceRuntimeView",
            {"tenant_id": self.tenant_id, "run_id": self.run_id},
        )


@dataclass(frozen=True)
class OpenBranchRequest:
    """Request to open a new branch in a stage."""

    run_id: str
    stage_id: str
    branch_id: str
    rationale: str = ""
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        _validate_spine(
            "OpenBranchRequest",
            {
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "stage_id": self.stage_id,
                "branch_id": self.branch_id,
            },
        )


@dataclass(frozen=True)
class BranchStateUpdateRequest:
    """Request to update a branch lifecycle state."""

    run_id: str
    branch_id: str
    target_state: BranchState
    failure_code: str | None = None
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        _validate_spine(
            "BranchStateUpdateRequest",
            {
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "branch_id": self.branch_id,
            },
        )


@dataclass(frozen=True)
class HumanGateRequest:
    """Request to open a human gate for approval."""

    run_id: str
    gate_type: str
    gate_ref: str
    context: dict[str, Any] = field(default_factory=dict)
    timeout_s: int = 3600
    # Explicit spine — preferred over context dict.
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""

    def __post_init__(self) -> None:
        _validate_spine(
            "HumanGateRequest",
            {"tenant_id": self.tenant_id, "run_id": self.run_id},
        )


@dataclass(frozen=True)
class ApprovalRequest:
    """Human approval or rejection of a gate."""

    gate_ref: str
    decision: str  # "approved" or "rejected"
    run_id: str = ""
    reviewer_id: str = ""
    comment: str = ""
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        # gate_ref is the primary identifier here — the run_id is optional
        # because some approval flows reference a gate that fans out to
        # multiple runs.
        _validate_spine(
            "ApprovalRequest",
            {"tenant_id": self.tenant_id, "gate_ref": self.gate_ref},
        )


@dataclass(frozen=True)
class KernelManifest:
    """Runtime capabilities and metadata."""

    version: str = "0.1.0"
    supported_substrates: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__

    def __post_init__(self) -> None:
        # KernelManifest has no run-scoped identifier; tenant_id + version
        # are the spine-equivalent identifiers for this manifest record.
        _validate_spine(
            "KernelManifest",
            {"tenant_id": self.tenant_id, "version": self.version},
        )


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
    fallback_events: list[dict] = field(default_factory=list)
    """Structured fallback events recorded during the run (Rule 7)."""
    llm_fallback_count: int = 0
    """Count of LLM/heuristic fallback events (gate-assertable scalar)."""
    finished_at: str | None = None
    """ISO-8601 UTC timestamp when the run reached a terminal state."""
    # Optional spine fields for HTTP body enrichment (Rule 12).
    tenant_id: str = ""  # scope: spine-required — validated in __post_init__
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""

    def __post_init__(self) -> None:
        _validate_spine(
            "RunResult",
            {"tenant_id": self.tenant_id, "run_id": self.run_id},
        )

    @property
    def success(self) -> bool:
        """Backward-compatible success flag used by async/integration callers."""
        return self.status == "completed"

    def __str__(self) -> str:
        return self.status

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.status == other
        if isinstance(other, RunResult):
            return self.status == other.status and self.run_id == other.run_id
        return NotImplemented

    def __hash__(self) -> int:
        # Hash matches the status string so `result in {"completed", "failed"}` works.
        return hash(self.status)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "stages": self.stages,
            "artifacts": self.artifacts,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "failure_code": self.failure_code,
            "failed_stage_id": self.failed_stage_id,
            "is_retryable": self.is_retryable,
            "execution_provenance": self.execution_provenance.to_dict()
            if self.execution_provenance
            else None,
            "fallback_events": self.fallback_events,
            "llm_fallback_count": self.llm_fallback_count,
            "finished_at": self.finished_at,
        }
        # Additive: include spine fields when non-empty (backwards-compatible).
        for _field in ("tenant_id", "user_id", "session_id", "project_id"):
            val = getattr(self, _field, "")
            if val:
                d[_field] = val
        return d

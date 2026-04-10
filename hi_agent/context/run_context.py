"""Per-run mutable state container for RunExecutor."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts import StageSummary, TrajectoryNode

try:
    from hi_agent.context.nudge import NudgeState
except ImportError:  # pragma: no cover
    NudgeState = None  # type: ignore[assignment,misc]

try:
    from hi_agent.task_view.result_budget import ToolResultBudgetState
except ImportError:  # pragma: no cover
    ToolResultBudgetState = None  # type: ignore[assignment,misc]


@dataclass
class RunContext:
    """Isolated mutable state for a single Run execution.

    Encapsulates all per-run mutable state that was previously scattered
    across RunExecutor instance variables. This enables:
    - Serialization/deserialization of run state for checkpoint/resume
    - Clear separation of configuration (RunExecutor) from state (RunContext)
    - Future support for run migration between executors
    """

    run_id: str
    dag: dict[str, TrajectoryNode] = field(default_factory=dict)
    stage_summaries: dict[str, StageSummary] = field(default_factory=dict)
    action_seq: int = 0
    branch_seq: int = 0
    decision_seq: int = 0
    current_stage: str = ""
    total_branches_opened: int = 0
    stage_active_branches: dict[str, int] = field(default_factory=dict)
    gate_seq: int = 0
    skill_ids_used: list[str] = field(default_factory=list)
    completed_stages: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    nudge_state: Any = field(
        default_factory=lambda: NudgeState() if NudgeState is not None else None
    )
    tool_result_budget_state: Any = field(
        default_factory=lambda: ToolResultBudgetState() if ToolResultBudgetState is not None else None
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize run context to a JSON-compatible dict."""
        return {
            "run_id": self.run_id,
            "dag": {k: _node_to_dict(v) for k, v in self.dag.items()},
            "stage_summaries": {
                k: _summary_to_dict(v) for k, v in self.stage_summaries.items()
            },
            "action_seq": self.action_seq,
            "branch_seq": self.branch_seq,
            "decision_seq": self.decision_seq,
            "current_stage": self.current_stage,
            "total_branches_opened": self.total_branches_opened,
            "stage_active_branches": dict(self.stage_active_branches),
            "gate_seq": self.gate_seq,
            "skill_ids_used": list(self.skill_ids_used),
            "completed_stages": sorted(self.completed_stages),
            "metadata": dict(self.metadata),
            "nudge_state": (
                self.nudge_state.to_dict()
                if self.nudge_state is not None
                else {}
            ),
            "tool_result_budget_state": (
                self.tool_result_budget_state.to_dict()
                if self.tool_result_budget_state is not None
                else {}
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunContext:
        """Deserialize run context from a dict."""
        ctx = cls(
            run_id=data["run_id"],
            action_seq=data.get("action_seq", 0),
            branch_seq=data.get("branch_seq", 0),
            decision_seq=data.get("decision_seq", 0),
            current_stage=data.get("current_stage", ""),
            total_branches_opened=data.get("total_branches_opened", 0),
            stage_active_branches=data.get("stage_active_branches", {}),
            gate_seq=data.get("gate_seq", 0),
            skill_ids_used=data.get("skill_ids_used", []),
            completed_stages=set(data.get("completed_stages", [])),
            metadata=data.get("metadata", {}),
        )
        if NudgeState is not None:
            ctx.nudge_state = NudgeState.from_dict(data.get("nudge_state", {}))
        if ToolResultBudgetState is not None:
            ctx.tool_result_budget_state = ToolResultBudgetState.from_dict(
                data.get("tool_result_budget_state", {})
            )
        return ctx


def _node_to_dict(node: TrajectoryNode) -> dict[str, Any]:
    """Convert TrajectoryNode to dict."""
    return {
        "node_id": node.node_id,
        "stage_id": node.stage_id,
        "state": node.state.value if hasattr(node.state, "value") else str(node.state),
        "node_type": (
            node.node_type.value
            if hasattr(node.node_type, "value")
            else str(node.node_type)
        ),
        "parent_ids": list(node.parent_ids),
    }


def _summary_to_dict(summary: StageSummary) -> dict[str, Any]:
    """Convert StageSummary to dict."""
    return {
        "stage_id": summary.stage_id,
        "stage_name": summary.stage_name,
        "findings": list(summary.findings),
        "decisions": list(summary.decisions),
        "open_questions": list(summary.open_questions),
        "outcome": summary.outcome,
    }


class RunContextManager:
    """Manages multiple concurrent RunContext instances.

    Thread-safe manager for looking up, creating, and removing
    per-run state containers.
    """

    def __init__(self) -> None:
        """Initialize RunContextManager."""
        self._contexts: dict[str, RunContext] = {}
        self._lock = threading.Lock()

    def create(self, run_id: str, **kwargs: Any) -> RunContext:
        """Create and register a new RunContext."""
        with self._lock:
            if run_id in self._contexts:
                raise ValueError(f"RunContext already exists for {run_id}")
            ctx = RunContext(run_id=run_id, **kwargs)
            self._contexts[run_id] = ctx
            return ctx

    def get(self, run_id: str) -> RunContext | None:
        """Get RunContext by run_id, or None if not found."""
        with self._lock:
            return self._contexts.get(run_id)

    def get_or_create(self, run_id: str, **kwargs: Any) -> RunContext:
        """Get existing or create new RunContext."""
        with self._lock:
            if run_id not in self._contexts:
                self._contexts[run_id] = RunContext(run_id=run_id, **kwargs)
            return self._contexts[run_id]

    def remove(self, run_id: str) -> RunContext | None:
        """Remove and return RunContext, or None if not found."""
        with self._lock:
            return self._contexts.pop(run_id, None)

    def list_runs(self) -> list[str]:
        """Return list of active run IDs."""
        with self._lock:
            return list(self._contexts.keys())

    @property
    def active_count(self) -> int:
        """Return number of active run contexts."""
        with self._lock:
            return len(self._contexts)

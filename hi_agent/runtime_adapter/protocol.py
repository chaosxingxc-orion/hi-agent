"""Runtime adapter protocol used by runner orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import (
    ApprovalRequest,
    HumanGateRequest,
)


class RuntimeAdapter(Protocol):
    """Runtime adapter behavior contract.

    Defines the 17-method surface that hi-agent uses to communicate with
    the agent-kernel runtime substrate.
    """

    # --- Stage lifecycle ---

    def open_stage(self, stage_id: str) -> None:
        """Open stage in runtime."""

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Update stage lifecycle state in runtime."""

    # --- Task view ---

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        """Persist task view payload and return stored task view ID."""

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        """Persist immutable binding between task-view and decision reference."""

    # --- Run lifecycle ---

    def start_run(self, task_id: str) -> str:
        """Start a run for task and return run ID."""

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Return run lifecycle snapshot."""

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel run with reason."""

    def resume_run(self, run_id: str) -> None:
        """Resume a suspended or cancelled run."""

    def signal_run(
        self, run_id: str, signal: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Push an external signal to a run."""

    # --- Trace runtime ---

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Return trace runtime snapshot for diagnostics/reconcile."""

    def stream_run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield run events as an async stream."""

    # --- Branch lifecycle ---

    def open_branch(self, run_id: str, stage_id: str, branch_id: str) -> None:
        """Create branch lifecycle record."""

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Update branch lifecycle state."""

    # --- Human gate ---

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open a human gate and block until resolved or timed out."""

    def submit_approval(self, request: ApprovalRequest) -> None:
        """Submit an approval or rejection for a pending human gate."""

    # --- Plan & manifest ---

    def get_manifest(self) -> dict[str, Any]:
        """Return runtime capabilities/metadata."""

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        """Persist execution plan for run."""


class RuntimeAdapterBackend(Protocol):
    """Optional backend hooks consumed by :class:`KernelAdapter`."""

    open_stage: Callable[[str], None] | None
    mark_stage_state: Callable[[str, StageState], None] | None
    record_task_view: Callable[[str, dict[str, Any]], str | None] | None
    start_run: Callable[[str], str | None] | None
    query_run: Callable[[str], dict[str, Any] | None] | None
    cancel_run: Callable[[str, str], None] | None
    signal_run: Callable[[str, str, dict[str, Any] | None], None] | None
    query_trace_runtime: Callable[[str], dict[str, Any] | None] | None
    bind_task_view_to_decision: Callable[[str, str], None] | None
    open_branch: Callable[[str, str, str], None] | None
    mark_branch_state: (
        Callable[[str, str, str, str, str | None], None] | None
    )
    resume_run: Callable[[str], None] | None
    get_manifest: Callable[[], dict[str, Any] | None] | None
    submit_plan: Callable[[str, dict[str, Any]], None] | None
    open_human_gate: Callable[[HumanGateRequest], None] | None
    submit_approval: Callable[[ApprovalRequest], None] | None
    stream_run_events: (
        Callable[[str], AsyncIterator[dict[str, Any]]] | None
    )


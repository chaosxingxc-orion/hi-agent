"""Runtime adapter protocol used by runner orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

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

    @property
    def mode(self) -> Literal["local-fsm", "http"]:
        """The kernel execution mode."""
        ...

    # --- Stage lifecycle ---

    def open_stage(self, run_id: str, stage_id: str) -> None:
        """Open stage in runtime."""

    def mark_stage_state(self, run_id: str, stage_id: str, target: StageState) -> None:
        """Update stage lifecycle state in runtime."""

    # --- Task view ---

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        """Persist task view payload and return stored task view ID."""

    def bind_task_view_to_decision(self, task_view_id: str, decision_ref: str) -> None:
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

    def signal_run(self, run_id: str, signal: str, payload: dict[str, Any] | None = None) -> None:
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

    # --- Run diagnostics ---

    def query_run_postmortem(self, run_id: str) -> Any:
        """Return postmortem view for a completed run."""

    # --- Child run management ---

    def spawn_child_run(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a child run under the given parent run. Returns child run_id."""

    def query_child_runs(self, parent_run_id: str) -> Any:
        """Query all child runs of the given parent run."""

    async def spawn_child_run_async(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Async version of spawn_child_run. Returns child run_id."""

    async def query_child_runs_async(self, parent_run_id: str) -> Any:
        """Async version of query_child_runs."""

    # --- Escalation resolution ---

    def resolve_escalation(
        self,
        run_id: str,
        *,
        resolution_notes: str | None = None,
        caused_by: str | None = None,
    ) -> None:
        """Resume a run stuck in waiting_external after human_escalation.

        Sends a ``recovery_succeeded`` signal to the workflow so execution
        can continue.  Corresponds to ``KernelFacade.resolve_escalation``
        (marked *Public caller-facing API* in agent-kernel).
        """

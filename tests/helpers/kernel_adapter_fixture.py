"""Test runtime adapter backed by real agent-kernel LocalFSM.

This helper preserves the historical MockKernel surface used by tests while
delegating runtime behavior to hi_agent's agent-kernel adapter.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import IllegalStateTransitionError, RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_facade_adapter import create_local_adapter

IllegalStateTransition = IllegalStateTransitionError

_BRANCH_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"active", "pruned", "failed"},
    "active": {"waiting", "succeeded", "failed", "pruned"},
    "waiting": {"active", "failed", "pruned"},
    "succeeded": set(),
    "failed": set(),
    "pruned": set(),
}

_STAGE_TRANSITIONS: dict[StageState, set[StageState]] = {
    StageState.PENDING: {StageState.ACTIVE},
    StageState.ACTIVE: {StageState.BLOCKED, StageState.COMPLETED, StageState.FAILED},
    StageState.BLOCKED: {StageState.ACTIVE, StageState.FAILED},
    StageState.COMPLETED: set(),
    StageState.FAILED: set(),
}


class MockKernel:
    """Compatibility test adapter using real agent-kernel implementation."""

    def __init__(self, *, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode
        self._adapter = create_local_adapter()
        self._external_to_actual_run_id: dict[str, str] = {}
        self._run_counter = 0
        self.stages: dict[str, StageState] = {}
        self.events: list[dict[str, Any]] = []
        self.task_views: dict[str, dict[str, Any]] = {}
        self.task_view_decisions: dict[str, str] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.branches: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.gates: dict[str, dict[str, Any]] = {}

    def _record(self, event_type: str, **payload: Any) -> None:
        self.events.append({"event_type": event_type, **payload})

    def _actual_run_id(self, run_id: str) -> str:
        return self._external_to_actual_run_id.get(run_id, run_id)

    def get_events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("event_type") == event_type]

    def assert_stage_state(self, stage_id: str, expected: StageState) -> None:
        actual = self.stages.get(stage_id)
        if actual != expected:
            raise AssertionError(f"{stage_id}: expected {expected}, got {actual}")

    def open_stage(self, run_id: str, stage_id: str) -> None:
        with contextlib.suppress(RuntimeAdapterBackendError):
            self._adapter.open_stage(run_id, stage_id)
        if stage_id in self.stages:
            return
        self.stages[stage_id] = StageState.PENDING
        self._record("StageOpened", stage_id=stage_id)

    def mark_stage_state(self, run_id: str, stage_id: str, target: StageState) -> None:
        current = self.stages.get(stage_id)
        if current is None:
            raise ValueError(f"Stage {stage_id} not opened")
        if current == target:
            return
        if self.strict_mode and target not in _STAGE_TRANSITIONS[current]:
            raise IllegalStateTransitionError(f"{stage_id}: {current} -> {target} is illegal")
        with contextlib.suppress(RuntimeAdapterBackendError):
            self._adapter.mark_stage_state(run_id, stage_id, target)
        self.stages[stage_id] = target
        self._record(
            "StageStateChanged",
            stage_id=stage_id,
            from_state=current,
            to_state=target,
        )

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        try:
            result = self._adapter.record_task_view(task_view_id, content)
        except RuntimeAdapterBackendError as exc:
            # Local test substrate may run without a task_view_log injected,
            # or may not have a current run context in unit tests.
            # Keep local mirror so integration tests can still assert task-view behavior.
            if "task_view_log" in str(exc) or "requires run context" in str(exc):
                result = task_view_id
            else:
                raise
        self.task_views.setdefault(task_view_id, content)
        self._record("TaskViewRecorded", task_view_id=task_view_id)
        return result

    def bind_task_view_to_decision(self, task_view_id: str, decision_ref: str) -> None:
        if task_view_id not in self.task_views:
            raise ValueError(f"Task view {task_view_id} not found")
        existing = self.task_view_decisions.get(task_view_id)
        if existing is not None and existing != decision_ref:
            raise ValueError(
                f"Task view {task_view_id} already bound to {existing}, cannot rebind to {decision_ref}"
            )
        try:
            self._adapter.bind_task_view_to_decision(task_view_id, decision_ref)
        except RuntimeAdapterBackendError as exc:
            if "task_view_log" not in str(exc) and "run context" not in str(exc):
                raise
        self.task_view_decisions[task_view_id] = decision_ref
        self._record(
            "TaskViewDecisionBound", task_view_id=task_view_id, decision_ref=decision_ref
        )

    def start_run(self, task_id: str) -> str:
        actual_run_id = self._adapter.start_run(task_id)
        self._run_counter += 1
        external_run_id = f"run-{self._run_counter:04d}"
        self._external_to_actual_run_id[external_run_id] = actual_run_id
        self.runs[external_run_id] = {
            "run_id": external_run_id,
            "task_id": task_id,
            "status": "running",
            "cancel_reason": None,
            "signals": [],
            "plan": None,
        }
        self._record("RunStarted", run_id=external_run_id, task_id=task_id)
        return external_run_id

    def query_run(self, run_id: str) -> dict[str, Any]:
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if run_id not in self.runs:
            raise ValueError(f"Run {run_id} not found")
        try:
            data = self._adapter.query_run(self._actual_run_id(run_id))
            if isinstance(data, dict):
                data = dict(data)
                data["run_id"] = run_id
                # Overlay MockKernel-tracked fields so tests can assert on them
                # alongside real kernel fields (e.g. lifecycle_state).
                local = self.runs[run_id]
                for k in ("status", "cancel_reason", "signals", "plan"):
                    if k in local:
                        data.setdefault(k, local[k])
                return data
        except Exception:
            pass
        if run_id in self.runs:
            return dict(self.runs[run_id])
        raise ValueError(f"Run {run_id} not found")

    def cancel_run(self, run_id: str, reason: str) -> None:
        self._adapter.cancel_run(self._actual_run_id(run_id), reason)
        if run_id in self.runs:
            self.runs[run_id]["status"] = "cancelled"
            self.runs[run_id]["cancel_reason"] = reason
        self._record("RunCancelled", run_id=run_id, reason=reason)

    def resume_run(self, run_id: str) -> None:
        state = self.runs.get(run_id, {}).get("status")
        if state in {"completed", "failed"}:
            raise IllegalStateTransitionError(f"{run_id}: {state} cannot resume")
        self._adapter.resume_run(self._actual_run_id(run_id))
        if run_id in self.runs:
            self.runs[run_id]["status"] = "running"
        self._record("RunResumed", run_id=run_id)

    def signal_run(self, run_id: str, signal: str, payload: dict[str, Any] | None = None) -> None:
        self._adapter.signal_run(self._actual_run_id(run_id), signal, payload)
        if run_id in self.runs:
            self.runs[run_id]["signals"].append({"signal": signal, "payload": payload or {}})
        self._record("RunSignaled", run_id=run_id, signal=signal)

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        return self._adapter.query_trace_runtime(self._actual_run_id(run_id))

    async def stream_run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        async for event in self._adapter.stream_run_events(self._actual_run_id(run_id)):
            yield event

    def open_branch(self, run_id: str, stage_id: str, branch_id: str) -> None:
        with contextlib.suppress(RuntimeAdapterBackendError):
            self._adapter.open_branch(self._actual_run_id(run_id), stage_id, branch_id)
        self.branches[(run_id, stage_id, branch_id)] = {
            "state": "proposed",
            "failure_code": None,
        }
        self._record("BranchOpened", run_id=run_id, stage_id=stage_id, branch_id=branch_id)

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        key = (run_id, stage_id, branch_id)
        current = self.branches.get(key, {}).get("state", "proposed")
        if current == state:
            return
        if self.strict_mode and state not in _BRANCH_TRANSITIONS.get(current, set()):
            raise IllegalStateTransitionError(f"{branch_id}: {current} -> {state} is illegal")
        with contextlib.suppress(RuntimeAdapterBackendError):
            self._adapter.mark_branch_state(
                self._actual_run_id(run_id), stage_id, branch_id, state, failure_code
            )
        self.branches[key] = {
            "state": state,
            "failure_code": failure_code,
        }
        self._record(
            "BranchStateChanged",
            run_id=run_id,
            stage_id=stage_id,
            branch_id=branch_id,
            from_state=current,
            to_state=state,
            failure_code=failure_code,
        )

    def open_human_gate(self, request: HumanGateRequest) -> None:
        actual_req = HumanGateRequest(
            run_id=self._actual_run_id(request.run_id),
            gate_type=request.gate_type,
            gate_ref=request.gate_ref,
            context=request.context,
            timeout_s=request.timeout_s,
        )
        self._adapter.open_human_gate(actual_req)
        self.gates[request.gate_ref] = {
            "run_id": request.run_id,
            "gate_type": request.gate_type,
            "resolved": False,
            "status": "pending",
        }
        self._record("HumanGateOpened", gate_ref=request.gate_ref, run_id=request.run_id)

    def submit_approval(self, request: ApprovalRequest) -> None:
        actual_req = ApprovalRequest(
            gate_ref=request.gate_ref,
            decision=request.decision,
            reviewer_id=request.reviewer_id,
            comment=request.comment,
        )
        self._adapter.submit_approval(actual_req)
        gate = self.gates.get(request.gate_ref)
        if gate is not None:
            gate["resolved"] = True
            gate["decision"] = request.decision
            gate["status"] = "resolved"
        self._record(
            "ApprovalSubmitted",
            gate_ref=request.gate_ref,
            decision=request.decision,
        )

    def get_manifest(self) -> dict[str, Any]:
        return self._adapter.get_manifest()

    def query_run_postmortem(self, run_id: str) -> Any:
        return self._adapter.query_run_postmortem(self._actual_run_id(run_id))

    def spawn_child_run(
        self, parent_run_id: str, task_id: str, config: dict[str, Any] | None = None
    ) -> str:
        return self._adapter.spawn_child_run(
            self._actual_run_id(parent_run_id), task_id, config
        )

    def query_child_runs(self, parent_run_id: str) -> list[dict[str, Any]]:
        return self._adapter.query_child_runs(self._actual_run_id(parent_run_id))

    async def spawn_child_run_async(
        self, parent_run_id: str, task_id: str, config: dict[str, Any] | None = None
    ) -> str:
        return await self._adapter.spawn_child_run_async(
            self._actual_run_id(parent_run_id), task_id, config
        )

    async def query_child_runs_async(self, parent_run_id: str) -> list[dict[str, Any]]:
        return await self._adapter.query_child_runs_async(
            self._actual_run_id(parent_run_id)
        )

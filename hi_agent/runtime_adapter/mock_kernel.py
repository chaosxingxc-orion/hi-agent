"""Mock kernel used by spike tests.

This adapter validates stage-state transitions and records in-memory events.
It mimics just enough behavior to verify run orchestration without depending
on external runtime systems.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from hi_agent.contracts import BranchState, StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import IllegalStateTransitionError

_STAGE_TRANSITIONS: dict[StageState, set[StageState]] = {
    StageState.PENDING: {StageState.ACTIVE},
    StageState.ACTIVE: {StageState.BLOCKED, StageState.COMPLETED, StageState.FAILED},
    StageState.BLOCKED: {StageState.ACTIVE, StageState.FAILED},
    StageState.COMPLETED: set(),
    StageState.FAILED: set(),
}

_BRANCH_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"active", "pruned", "failed"},
    "active": {"waiting", "succeeded", "failed", "pruned"},
    "waiting": {"active", "failed", "pruned"},
    "succeeded": set(),
    "failed": set(),
    "pruned": set(),
}

# Valid gate types matching CLAUDE.md Human Gate Types.
_VALID_GATE_TYPES = frozenset({
    "contract_correction",
    "route_direction",
    "artifact_review",
    "final_approval",
})

# Valid approval decisions.
_VALID_DECISIONS = frozenset({"approved", "rejected"})


class MockKernel:
    """In-memory runtime kernel with optional strict transition validation."""

    def __init__(self, *, strict_mode: bool = True) -> None:
        """Initialize in-memory kernel state.

        Args:
          strict_mode: Whether to enforce stage transition legality.
        """
        self.strict_mode = strict_mode
        self.stages: dict[str, StageState] = {}
        self.events: list[dict] = []
        self.task_views: dict[str, dict] = {}
        self.task_view_decisions: dict[str, str] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.branches: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.gates: dict[str, dict[str, Any]] = {}
        self._run_counter = 0

    def open_stage(self, stage_id: str) -> None:
        """Open stage in PENDING state.

        Calling this repeatedly is idempotent.
        """
        if stage_id in self.stages:
            return
        self.stages[stage_id] = StageState.PENDING
        self._record("StageOpened", stage_id=stage_id)

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Transition stage to target state.

        Args:
          stage_id: Stage to update.
          target: Desired target state.

        Raises:
          ValueError: If stage has not been opened.
          IllegalStateTransitionError: If transition is illegal in strict mode.
        """
        current = self.stages.get(stage_id)
        if current is None:
            raise ValueError(f"Stage {stage_id} not opened")
        if current == target:
            return
        if self.strict_mode and target not in _STAGE_TRANSITIONS[current]:
            raise IllegalStateTransitionError(f"{stage_id}: {current} -> {target} is illegal")
        self.stages[stage_id] = target
        self._record(
            "StageStateChanged",
            stage_id=stage_id,
            from_state=current,
            to_state=target,
        )

    def record_task_view(self, task_view_id: str, content: dict) -> str:
        """Record task view content idempotently."""
        if task_view_id in self.task_views:
            return task_view_id
        self.task_views[task_view_id] = content
        self._record("TaskViewRecorded", task_view_id=task_view_id)
        return task_view_id

    def start_run(self, task_id: str) -> str:
        """Start run with deterministic run ID generation."""
        normalized_task_id = self._validate_non_empty(task_id, "task_id")
        self._run_counter += 1
        run_id = f"run-{self._run_counter:04d}"
        self.runs[run_id] = {
            "run_id": run_id,
            "task_id": normalized_task_id,
            "status": "running",
            "cancel_reason": None,
            "signals": [],
            "plan": None,
        }
        self._record("RunStarted", run_id=run_id, task_id=normalized_task_id)
        return run_id

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Return run lifecycle snapshot."""
        run = self._get_run(run_id)
        return {
            "run_id": run["run_id"],
            "task_id": run["task_id"],
            "status": run["status"],
            "cancel_reason": run["cancel_reason"],
            "signals": list(run["signals"]),
            "plan": run["plan"],
        }

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel run and persist cancellation reason."""
        normalized_reason = self._validate_non_empty(reason, "reason")
        run = self._get_run(run_id)
        if run["status"] == "cancelled":
            return
        run["status"] = "cancelled"
        run["cancel_reason"] = normalized_reason
        self._record("RunCancelled", run_id=run_id, reason=normalized_reason)

    def signal_run(self, run_id: str, signal: str, payload: dict[str, Any] | None = None) -> None:
        """Append an external signal to run state and event stream."""
        run = self._get_run(run_id)
        normalized_signal = self._validate_non_empty(signal, "signal")
        normalized_payload = payload or {}
        if not isinstance(normalized_payload, dict):
            raise ValueError("payload must be a dict when provided")
        run["signals"].append(
            {
                "signal": normalized_signal,
                "payload": dict(normalized_payload),
            }
        )
        self._record(
            "RunSignaled",
            run_id=run_id,
            signal=normalized_signal,
            payload=dict(normalized_payload),
        )

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Build a deterministic runtime snapshot used by ops and replay checks."""
        run = self._get_run(run_id)
        branch_rows = [
            {
                "run_id": key[0],
                "stage_id": key[1],
                "branch_id": key[2],
                "state": value["state"],
                "failure_code": value.get("failure_code"),
            }
            for key, value in self.branches.items()
            if key[0] == run_id
        ]
        branch_rows.sort(key=lambda item: (item["stage_id"], item["branch_id"]))
        task_view_bindings = {
            task_view_id: decision_ref
            for task_view_id, decision_ref in self.task_view_decisions.items()
            if self.task_views.get(task_view_id, {}).get("run_id", run_id) == run_id
        }
        return {
            "run": dict(run),
            "stages": {stage_id: state.value for stage_id, state in sorted(self.stages.items())},
            "branches": branch_rows,
            "task_view_bindings": task_view_bindings,
            "signals": list(run["signals"]),
            "plan": run["plan"],
        }

    def bind_task_view_to_decision(self, task_view_id: str, decision_ref: str) -> None:
        """Bind a task view to a decision reference with conflict validation."""
        normalized_task_view_id = self._validate_non_empty(task_view_id, "task_view_id")
        normalized_decision_ref = self._validate_non_empty(decision_ref, "decision_ref")
        if normalized_task_view_id not in self.task_views:
            raise ValueError(f"Task view {normalized_task_view_id} not found")
        existing = self.task_view_decisions.get(normalized_task_view_id)
        if existing is not None and existing != normalized_decision_ref:
            raise ValueError(
                f"Task view {normalized_task_view_id} already bound to {existing}, "
                f"cannot rebind to {normalized_decision_ref}"
            )
        self.task_view_decisions[normalized_task_view_id] = normalized_decision_ref
        self._record(
            "TaskViewDecisionBound",
            task_view_id=normalized_task_view_id,
            decision_ref=normalized_decision_ref,
        )

    def open_branch(self, run_id: str, stage_id: str, branch_id: str) -> None:
        """Create branch entry in proposed state; operation is idempotent."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        normalized_stage_id = self._validate_non_empty(stage_id, "stage_id")
        normalized_branch_id = self._validate_non_empty(branch_id, "branch_id")
        self._get_run(normalized_run_id)
        key = (normalized_run_id, normalized_stage_id, normalized_branch_id)
        if key in self.branches:
            return
        self.branches[key] = {
            "state": "proposed",
            "failure_code": None,
        }
        self._record(
            "BranchOpened",
            run_id=normalized_run_id,
            stage_id=normalized_stage_id,
            branch_id=normalized_branch_id,
        )

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Transition branch state using a strict lifecycle model."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        normalized_stage_id = self._validate_non_empty(stage_id, "stage_id")
        normalized_branch_id = self._validate_non_empty(branch_id, "branch_id")
        normalized_state = self._validate_non_empty(state, "state")
        if normalized_state not in _BRANCH_TRANSITIONS:
            raise ValueError(f"Unknown branch state: {normalized_state}")

        key = (normalized_run_id, normalized_stage_id, normalized_branch_id)
        branch = self.branches.get(key)
        if branch is None:
            raise ValueError(
                f"Branch not found: run_id={normalized_run_id} "
                f"stage_id={normalized_stage_id} branch_id={normalized_branch_id}"
            )

        current_state = branch["state"]
        if current_state == normalized_state:
            return
        if self.strict_mode and normalized_state not in _BRANCH_TRANSITIONS[current_state]:
            raise IllegalStateTransitionError(
                f"branch {normalized_branch_id}: {current_state} -> {normalized_state} is illegal"
            )
        if normalized_state == "failed" and failure_code is not None:
            branch["failure_code"] = self._validate_non_empty(failure_code, "failure_code")
        elif normalized_state != "failed":
            branch["failure_code"] = None
        branch["state"] = normalized_state
        self._record(
            "BranchStateChanged",
            run_id=normalized_run_id,
            stage_id=normalized_stage_id,
            branch_id=normalized_branch_id,
            from_state=current_state,
            to_state=normalized_state,
            failure_code=branch["failure_code"],
        )

    def resume_run(self, run_id: str) -> None:
        """Resume run from cancelled/waiting state to running state."""
        run = self._get_run(run_id)
        if run["status"] == "running":
            return
        if run["status"] in {"completed", "failed"}:
            raise IllegalStateTransitionError(f"Run {run_id} in terminal state: {run['status']}")
        run["status"] = "running"
        run["cancel_reason"] = None
        self._record("RunResumed", run_id=run_id)

    def get_manifest(self) -> dict[str, Any]:
        """Return deterministic manifest for runtime capabilities."""
        return {
            "name": "mock_kernel",
            "strict_mode": self.strict_mode,
            "supported_methods": [
                "open_stage",
                "mark_stage_state",
                "record_task_view",
                "start_run",
                "query_run",
                "cancel_run",
                "signal_run",
                "query_trace_runtime",
                "bind_task_view_to_decision",
                "open_branch",
                "mark_branch_state",
                "resume_run",
                "get_manifest",
                "submit_plan",
                "open_human_gate",
                "submit_approval",
                "stream_run_events",
            ],
        }

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        """Persist execution plan payload for a run."""
        run = self._get_run(run_id)
        if not isinstance(plan, dict):
            raise ValueError("plan must be a dict")
        run["plan"] = dict(plan)
        self._record("PlanSubmitted", run_id=run_id, plan=dict(plan))

    # --- Human gate methods ---

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open a human gate and record it as pending.

        Idempotent: opening the same gate_ref twice is a no-op.

        Raises:
          ValueError: If the run does not exist or gate_type is invalid.
        """
        self._get_run(request.run_id)
        gate_type = self._validate_non_empty(request.gate_type, "gate_type")
        gate_ref = self._validate_non_empty(request.gate_ref, "gate_ref")
        if gate_type not in _VALID_GATE_TYPES:
            raise ValueError(
                f"Unknown gate_type: {gate_type}; "
                f"valid types: {sorted(_VALID_GATE_TYPES)}"
            )
        if gate_ref in self.gates:
            return
        self.gates[gate_ref] = {
            "run_id": request.run_id,
            "gate_type": gate_type,
            "gate_ref": gate_ref,
            "context": dict(request.context),
            "timeout_s": request.timeout_s,
            "status": "pending",
            "decision": None,
            "reviewer_id": None,
            "comment": None,
        }
        self._record(
            "HumanGateOpened",
            run_id=request.run_id,
            gate_type=gate_type,
            gate_ref=gate_ref,
        )

    def submit_approval(self, request: ApprovalRequest) -> None:
        """Submit an approval or rejection for a pending human gate.

        Idempotent: submitting the same decision for an already-resolved
        gate with the same decision is a no-op.

        Raises:
          ValueError: If the gate_ref is unknown, the decision is invalid,
            or the gate has already been resolved with a different decision.
        """
        gate_ref = self._validate_non_empty(request.gate_ref, "gate_ref")
        decision = self._validate_non_empty(request.decision, "decision")
        if decision not in _VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision: {decision}; "
                f"valid decisions: {sorted(_VALID_DECISIONS)}"
            )
        gate = self.gates.get(gate_ref)
        if gate is None:
            raise ValueError(f"Gate {gate_ref} not found")
        if gate["status"] == "resolved":
            if gate["decision"] == decision:
                return  # idempotent
            raise ValueError(
                f"Gate {gate_ref} already resolved as "
                f"'{gate['decision']}', cannot change to '{decision}'"
            )
        gate["status"] = "resolved"
        gate["decision"] = decision
        gate["reviewer_id"] = request.reviewer_id or None
        gate["comment"] = request.comment or None
        self._record(
            "HumanGateResolved",
            gate_ref=gate_ref,
            decision=decision,
            reviewer_id=gate["reviewer_id"],
        )

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield recorded events for the given run as an async stream.

        Only events that contain a matching run_id field are yielded.
        """
        self._get_run(run_id)
        for event in self.events:
            if event.get("run_id") == run_id:
                yield dict(event)

    def assert_stage_state(self, stage_id: str, expected: StageState) -> None:
        """Assert helper for tests."""
        actual = self.stages.get(stage_id)
        assert actual == expected, f"Stage {stage_id}: expected {expected}, got {actual}"

    def get_events_of_type(self, event_type: str) -> list[dict]:
        """Filter event list by event type."""
        return [event for event in self.events if event["event_type"] == event_type]

    def _record(self, event_type: str, **payload: object) -> None:
        """Append an event entry to in-memory log."""
        self.events.append({"event_type": event_type, **payload})

    def _get_run(self, run_id: str) -> dict[str, Any]:
        """Resolve run by ID with strict existence validation."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        run = self.runs.get(normalized_run_id)
        if run is None:
            raise ValueError(f"Run {normalized_run_id} not found")
        return run

    def _validate_non_empty(self, value: str, field_name: str) -> str:
        """Validate non-empty string values under strict mode semantics."""
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must be a non-empty string")
        return normalized


# Backward-compatible alias to match spike docs/test naming.
IllegalStateTransition = IllegalStateTransitionError

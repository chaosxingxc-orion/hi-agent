"""Kernel adapter for production-facing runtime integration.

The adapter uses an optional backend object so integration can run in two
modes:
1) In-memory fallback (default in local tests and when backend unavailable).
2) Delegation mode with a provided backend that exposes compatible methods.
"""

from __future__ import annotations

from typing import Any

from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.consistency import (
    ConsistencyIssue,
    InMemoryConsistencyJournal,
)
from hi_agent.runtime_adapter.errors import (
    IllegalStateTransitionError,
    RuntimeAdapterBackendError,
)
from hi_agent.runtime_adapter.kernel_backend import KernelBackend
from hi_agent.runtime_adapter.protocol import RuntimeAdapterBackend

_STAGE_TRANSITIONS: dict[StageState, set[StageState]] = {
    StageState.PENDING: {StageState.ACTIVE},
    StageState.ACTIVE: {StageState.BLOCKED, StageState.COMPLETED, StageState.FAILED},
    StageState.BLOCKED: {StageState.ACTIVE, StageState.FAILED},
    StageState.COMPLETED: set(),
    StageState.FAILED: set(),
}


class KernelAdapter:
    """Runtime adapter with optional delegated backend.

    If a backend is passed and has matching methods, this class forwards calls
    to that backend while preserving strict transition validation locally.
    """

    def __init__(
        self,
        *,
        strict_mode: bool = True,
        backend: RuntimeAdapterBackend | KernelBackend | None = None,
        consistency_journal: InMemoryConsistencyJournal | None = None,
    ) -> None:
        """Initialize adapter state.

        Args:
          strict_mode: Whether to enforce stage transition legality.
          backend: Optional backend that may expose adapter-compatible hooks.
          consistency_journal: Optional journal used to record local/backend
            consistency issues.
        """
        self.strict_mode = strict_mode
        self.backend = backend
        self.consistency_journal = consistency_journal or InMemoryConsistencyJournal()
        self.stages: dict[str, StageState] = {}
        self.events: list[dict] = []
        self.task_views: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.task_view_decisions: dict[str, str] = {}
        self.branches: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._run_counter = 0

    def open_stage(self, stage_id: str) -> None:
        """Open stage in PENDING state and notify backend if available.

        Consistency strategy: local state and local event log are committed
        before backend delegation. If backend write fails, local write is kept
        and the external system should be reconciled asynchronously.
        """
        if stage_id in self.stages:
            return
        self.stages[stage_id] = StageState.PENDING
        self._record("StageOpened", stage_id=stage_id)
        self._call_backend("open_stage", stage_id)

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Transition stage state with strict validation."""
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
        self._call_backend("mark_stage_state", stage_id, target)

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        """Record task view and notify backend if supported."""
        if task_view_id in self.task_views:
            return task_view_id
        self.task_views[task_view_id] = content
        self._record("TaskViewRecorded", task_view_id=task_view_id)

        self._call_backend("record_task_view", task_view_id, content)

        return task_view_id

    def start_run(self, task_id: str) -> str:
        """Create run locally and delegate to backend when available."""
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
        backend_result = self._call_backend("start_run", normalized_task_id)
        if isinstance(backend_result, str) and backend_result.strip():
            run_id = backend_result
            self.runs[run_id] = self.runs.pop(f"run-{self._run_counter:04d}")
            self.runs[run_id]["run_id"] = run_id
        return run_id

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Resolve run snapshot by ID."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        run = self.runs.get(normalized_run_id)
        if run is None:
            raise ValueError(f"Run {normalized_run_id} not found")
        backend_result = self._call_backend("query_run", normalized_run_id)
        if isinstance(backend_result, dict):
            return dict(backend_result)
        return dict(run)

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel run and persist cancellation reason."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        normalized_reason = self._validate_non_empty(reason, "reason")
        run = self.runs.get(normalized_run_id)
        if run is None:
            raise ValueError(f"Run {normalized_run_id} not found")
        if run["status"] == "cancelled":
            return
        run["status"] = "cancelled"
        run["cancel_reason"] = normalized_reason
        self._record("RunCancelled", run_id=normalized_run_id, reason=normalized_reason)
        self._call_backend("cancel_run", normalized_run_id, normalized_reason)

    def signal_run(self, run_id: str, signal: str, payload: dict[str, Any] | None = None) -> None:
        """Append signal payload to run and forward to backend."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        normalized_signal = self._validate_non_empty(signal, "signal")
        run = self.runs.get(normalized_run_id)
        if run is None:
            raise ValueError(f"Run {normalized_run_id} not found")
        normalized_payload = payload or {}
        if not isinstance(normalized_payload, dict):
            raise ValueError("payload must be a dict when provided")
        run["signals"].append({"signal": normalized_signal, "payload": dict(normalized_payload)})
        self._record(
            "RunSignaled",
            run_id=normalized_run_id,
            signal=normalized_signal,
            payload=dict(normalized_payload),
        )
        self._call_backend("signal_run", normalized_run_id, normalized_signal, normalized_payload)

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Return deterministic runtime snapshot for diagnostics and replay checks."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        backend_result = self._call_backend("query_trace_runtime", normalized_run_id)
        if isinstance(backend_result, dict):
            return dict(backend_result)
        run = self.query_run(normalized_run_id)
        branches = [
            {
                "run_id": key[0],
                "stage_id": key[1],
                "branch_id": key[2],
                "state": value["state"],
                "failure_code": value.get("failure_code"),
            }
            for key, value in self.branches.items()
            if key[0] == normalized_run_id
        ]
        branches.sort(key=lambda item: (item["stage_id"], item["branch_id"]))
        return {
            "run": run,
            "stages": {stage_id: state.value for stage_id, state in sorted(self.stages.items())},
            "branches": branches,
            "task_view_bindings": dict(self.task_view_decisions),
            "signals": list(self.runs[normalized_run_id]["signals"]),
            "plan": self.runs[normalized_run_id]["plan"],
        }

    def bind_task_view_to_decision(self, task_view_id: str, decision_ref: str) -> None:
        """Bind task-view ID to decision reference idempotently."""
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
        self._call_backend(
            "bind_task_view_to_decision",
            normalized_task_view_id,
            normalized_decision_ref,
        )

    def open_branch(self, run_id: str, stage_id: str, branch_id: str) -> None:
        """Create branch record for a run-stage tuple."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        normalized_stage_id = self._validate_non_empty(stage_id, "stage_id")
        normalized_branch_id = self._validate_non_empty(branch_id, "branch_id")
        if normalized_run_id not in self.runs:
            raise ValueError(f"Run {normalized_run_id} not found")
        key = (normalized_run_id, normalized_stage_id, normalized_branch_id)
        if key in self.branches:
            return
        self.branches[key] = {"state": "proposed", "failure_code": None}
        self._record(
            "BranchOpened",
            run_id=normalized_run_id,
            stage_id=normalized_stage_id,
            branch_id=normalized_branch_id,
        )
        self._call_backend(
            "open_branch",
            normalized_run_id,
            normalized_stage_id,
            normalized_branch_id,
        )

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Update branch state and keep failure code on failed transitions."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        normalized_stage_id = self._validate_non_empty(stage_id, "stage_id")
        normalized_branch_id = self._validate_non_empty(branch_id, "branch_id")
        normalized_state = self._validate_non_empty(state, "state")
        key = (normalized_run_id, normalized_stage_id, normalized_branch_id)
        branch = self.branches.get(key)
        if branch is None:
            raise ValueError(
                f"Branch not found: run_id={normalized_run_id} "
                f"stage_id={normalized_stage_id} branch_id={normalized_branch_id}"
            )
        branch["state"] = normalized_state
        branch["failure_code"] = (
            self._validate_non_empty(failure_code, "failure_code")
            if normalized_state == "failed" and failure_code is not None
            else None
        )
        self._record(
            "BranchStateChanged",
            run_id=normalized_run_id,
            stage_id=normalized_stage_id,
            branch_id=normalized_branch_id,
            to_state=normalized_state,
            failure_code=branch["failure_code"],
        )
        self._call_backend(
            "mark_branch_state",
            normalized_run_id,
            normalized_stage_id,
            normalized_branch_id,
            normalized_state,
            branch["failure_code"],
        )

    def resume_run(self, run_id: str) -> None:
        """Resume run from waiting/cancelled to running."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        run = self.runs.get(normalized_run_id)
        if run is None:
            raise ValueError(f"Run {normalized_run_id} not found")
        if run["status"] == "running":
            return
        if run["status"] in {"completed", "failed"}:
            raise IllegalStateTransitionError(
                f"Run {normalized_run_id} in terminal state {run['status']}"
            )
        run["status"] = "running"
        run["cancel_reason"] = None
        self._record("RunResumed", run_id=normalized_run_id)
        self._call_backend("resume_run", normalized_run_id)

    def get_manifest(self) -> dict[str, Any]:
        """Return runtime manifest including supported methods."""
        backend_result = self._call_backend("get_manifest")
        if isinstance(backend_result, dict):
            return dict(backend_result)
        return {
            "name": "kernel_adapter",
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
            ],
        }

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        """Attach plan payload to run for replay and audit."""
        normalized_run_id = self._validate_non_empty(run_id, "run_id")
        if normalized_run_id not in self.runs:
            raise ValueError(f"Run {normalized_run_id} not found")
        if not isinstance(plan, dict):
            raise ValueError("plan must be a dict")
        self.runs[normalized_run_id]["plan"] = dict(plan)
        self._record("PlanSubmitted", run_id=normalized_run_id, plan=dict(plan))
        self._call_backend("submit_plan", normalized_run_id, dict(plan))

    def assert_stage_state(self, stage_id: str, expected: StageState) -> None:
        """Assert helper used by integration tests."""
        actual = self.stages.get(stage_id)
        assert actual == expected, f"Stage {stage_id}: expected {expected}, got {actual}"

    def get_events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        """Filter event list by type."""
        return [event for event in self.events if event["event_type"] == event_type]

    def _record(self, event_type: str, **payload: Any) -> None:
        """Append an event to in-memory log."""
        self.events.append({"event_type": event_type, **payload})

    def _call_backend(self, operation: str, *args: Any) -> Any | None:
        """Invoke backend hook if available and wrap backend failures."""
        if self.backend is None:
            return None

        hook = getattr(self.backend, operation, None)
        if not callable(hook):
            if self.strict_mode:
                missing = NotImplementedError(f"Backend does not implement '{operation}'")
                self.consistency_journal.append(
                    ConsistencyIssue(
                        operation=operation,
                        context=self._build_issue_context(operation, args),
                        error=str(missing),
                    )
                )
                raise RuntimeAdapterBackendError(operation, cause=missing) from missing
            return None

        try:
            return hook(*args)
        except Exception as exc:  # pragma: no cover - validated by integration tests
            self.consistency_journal.append(
                ConsistencyIssue(
                    operation=operation,
                    context=self._build_issue_context(operation, args),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise RuntimeAdapterBackendError(operation, cause=exc) from exc

    def _build_issue_context(self, operation: str, args: tuple[Any, ...]) -> dict[str, Any]:
        """Extract operation context for compensation handling."""
        context: dict[str, Any] = {}

        if operation == "open_stage" and args:
            context["stage_id"] = args[0]
        elif operation == "mark_stage_state" and len(args) >= 2:
            context["stage_id"] = args[0]
            context["target_state"] = str(args[1])
        elif operation == "record_task_view" and args:
            context["task_view_id"] = args[0]
            if len(args) >= 2 and isinstance(args[1], dict):
                if "stage_id" in args[1]:
                    context["stage_id"] = args[1]["stage_id"]
                if "run_id" in args[1]:
                    context["run_id"] = args[1]["run_id"]
        elif operation in {"query_run", "resume_run"} and args:
            context["run_id"] = args[0]
        elif operation == "cancel_run" and args:
            context["run_id"] = args[0]
            if len(args) >= 2:
                context["reason"] = args[1]
        elif operation == "signal_run" and args:
            context["run_id"] = args[0]
            if len(args) >= 2:
                context["signal"] = args[1]
        elif operation == "bind_task_view_to_decision" and len(args) >= 2:
            context["task_view_id"] = args[0]
            context["decision_ref"] = args[1]
        elif operation == "open_branch" and len(args) >= 3:
            context["run_id"] = args[0]
            context["stage_id"] = args[1]
            context["branch_id"] = args[2]
        elif operation == "mark_branch_state" and len(args) >= 4:
            context["run_id"] = args[0]
            context["stage_id"] = args[1]
            context["branch_id"] = args[2]
            context["state"] = args[3]
        elif operation == "submit_plan" and len(args) >= 2:
            context["run_id"] = args[0]

        return context

    def _validate_non_empty(self, value: str, field_name: str) -> str:
        """Normalize and validate required string values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must be a non-empty string")
        return normalized

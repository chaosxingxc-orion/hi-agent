"""Unit tests for RecoveryCoordinator extraction."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hi_agent.contracts import TaskContract
from hi_agent.execution.recovery_coordinator import (
    RecoveryContext,
    RecoveryCoordinator,
)


def _make_context(**overrides: Any) -> RecoveryContext:
    events: list[tuple[str, dict]] = []

    values = {
        "event_emitter": SimpleNamespace(events=[]),
        "recovery_executor": lambda _events: {"success": True},
        "recovery_handlers": None,
        "_recovery_executor_accepts_handlers": False,
        "_record_event": lambda event_type, payload: events.append((event_type, payload)),
        "_log_best_effort_exception": lambda *_args, **_kwargs: None,
        "run_id": "run-test",
        "_resolve_failed_stage_count": lambda _report: None,
        "_run_terminated": False,
        "_restart_policy": None,
        "_stage_attempt": {},
        "contract": TaskContract(task_id="task-test", goal="test goal"),
        "short_term_store": None,
        "context_manager": None,
        "_reflection_orchestrator": None,
        "_execute_stage": lambda _stage_id: "failed",
        "_get_attempt_history": lambda _stage_id: [],
        "_pending_reflection_tasks": [],
    }
    values.update(overrides)
    return RecoveryContext(**values)


def test_parse_forced_fail_empty() -> None:
    assert RecoveryCoordinator._parse_forced_fail_actions([]) == set()


def test_parse_forced_fail_with_value() -> None:
    constraints = ["other:value", "fail_action:search", "fail_action: write "]

    assert RecoveryCoordinator._parse_forced_fail_actions(constraints) == {
        "search",
        "write",
    }


def test_recovery_coordinator_creates() -> None:
    coordinator = RecoveryCoordinator(_make_context())

    assert coordinator is not None


def test_resolve_success_no_restart_policy() -> None:
    coordinator = RecoveryCoordinator(_make_context(_restart_policy=None))

    assert coordinator._handle_stage_failure("S1", "failed") == "failed"


def test_resolve_escalate_no_policy() -> None:
    class _RestartPolicy:
        def __init__(self) -> None:
            self.attempts: list[object] = []

        def _record_attempt(self, attempt: object) -> None:
            self.attempts.append(attempt)

        def _get_policy(self, _task_id: str) -> None:
            return None

    restart_policy = _RestartPolicy()
    coordinator = RecoveryCoordinator(_make_context(_restart_policy=restart_policy))

    assert coordinator._handle_stage_failure("S1", "failed") == "failed"
    assert len(restart_policy.attempts) == 1

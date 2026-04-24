"""Tests for hi_agent.task_mgmt.restart_policy."""

from __future__ import annotations

import importlib
import warnings
from datetime import UTC, datetime
from typing import Any

import pytest
from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine, TaskAttempt, TaskRestartPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_attempt(task_id: str, seq: int, outcome: str = "failed") -> TaskAttempt:
    return TaskAttempt(
        attempt_id=f"att-{seq}",
        task_id=task_id,
        run_id=f"run-{seq}",
        attempt_seq=seq,
        started_at=datetime(2026, 1, 1, 0, seq, tzinfo=UTC).isoformat(),
        outcome=outcome,
    )


def _build_engine(
    attempts: list[TaskAttempt] | None = None,
    policy: TaskRestartPolicy | None = None,
    retry_launcher: Any = None,
    reflection_handler: Any = None,
) -> tuple[RestartPolicyEngine, dict[str, Any]]:
    """Build a RestartPolicyEngine with in-memory state tracking."""
    _attempts = list(attempts or [])
    _policy = policy or TaskRestartPolicy()
    state_log: dict[str, Any] = {"states": [], "recorded": []}

    def get_attempts(task_id: str) -> list[TaskAttempt]:
        return [a for a in _attempts if a.task_id == task_id]

    def get_policy(task_id: str) -> TaskRestartPolicy | None:
        return _policy

    def update_state(task_id: str, state: str) -> None:
        state_log["states"].append((task_id, state))

    def record_attempt(attempt: TaskAttempt) -> None:
        _attempts.append(attempt)
        state_log["recorded"].append(attempt)

    engine = RestartPolicyEngine(
        get_attempts=get_attempts,
        get_policy=get_policy,
        update_state=update_state,
        record_attempt=record_attempt,
        retry_launcher=retry_launcher,
        reflection_handler=reflection_handler,
    )
    return engine, state_log


def _get_task_attempt_record_alias() -> type[TaskAttempt]:
    """Fetch the deprecated alias and assert it warns."""
    module = importlib.import_module("hi_agent.task_mgmt.restart_policy")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        alias = module.TaskAttemptRecord
    assert any(item.category is DeprecationWarning for item in caught)
    assert alias is TaskAttempt
    return alias


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_retry_within_budget():
    """Returns 'retry' when attempts < max_attempts and on_exhausted != 'reflect'."""
    policy = TaskRestartPolicy(
        max_attempts=3, on_exhausted="escalate", backoff_base_ms=0, max_backoff_ms=0
    )
    attempts = [_make_attempt("t1", 1)]
    task_attempt_record = _get_task_attempt_record_alias()

    async def launcher(task_id: str, seq: int) -> str:
        return f"new-run-{seq}"

    engine, _ = _build_engine(attempts=attempts, policy=policy, retry_launcher=launcher)

    decision = await engine.handle_failure("t1", "run-1")
    assert decision.action == "retry"
    assert decision.next_attempt_seq == 2
    assert task_attempt_record is TaskAttempt


@pytest.mark.asyncio
async def test_decide_escalate_on_exhaustion():
    """Returns 'escalate' when retry budget exhausted and on_exhausted='escalate'."""
    policy = TaskRestartPolicy(max_attempts=2, on_exhausted="escalate")
    attempts = [_make_attempt("t1", 1), _make_attempt("t1", 2)]
    engine, state_log = _build_engine(attempts=attempts, policy=policy)

    decision = await engine.handle_failure("t1", "run-2")
    assert decision.action == "escalate"
    assert decision.next_attempt_seq is None
    assert ("t1", "escalated") in state_log["states"]


@pytest.mark.asyncio
async def test_decide_reflect_on_exhaustion():
    """Returns 'reflect' when retry budget exhausted and on_exhausted='reflect'."""
    policy = TaskRestartPolicy(max_attempts=1, on_exhausted="reflect")
    attempts = [_make_attempt("t1", 1)]
    engine, state_log = _build_engine(attempts=attempts, policy=policy)

    decision = await engine.handle_failure("t1", "run-1")
    assert decision.action == "reflect"
    assert ("t1", "reflecting") in state_log["states"]


@pytest.mark.asyncio
async def test_decide_abort_on_non_retryable():
    """Non-retryable failure goes to on_exhausted policy immediately."""
    policy = TaskRestartPolicy(max_attempts=5, on_exhausted="abort")

    class _Failure:
        retryability = "non_retryable"
        failure_code = "unsafe_action_blocked"

    attempts = [_make_attempt("t1", 1)]
    engine, state_log = _build_engine(attempts=attempts, policy=policy)

    decision = await engine.handle_failure("t1", "run-1", failure=_Failure())
    assert decision.action == "abort"
    assert "non_retryable" in decision.reason
    assert ("t1", "aborted") in state_log["states"]


@pytest.mark.asyncio
async def test_handle_failure_retry_launches_new_run():
    """handle_failure with a retry_launcher actually launches a new run."""
    policy = TaskRestartPolicy(
        max_attempts=3, on_exhausted="escalate", backoff_base_ms=0, max_backoff_ms=0
    )
    attempts = [_make_attempt("t1", 1)]

    async def launcher(task_id: str, seq: int) -> str:
        return f"new-run-{seq}"

    engine, state_log = _build_engine(
        attempts=attempts,
        policy=policy,
        retry_launcher=launcher,
    )

    decision = await engine.handle_failure("t1", "run-1")
    assert decision.action == "retry"
    assert len(state_log["recorded"]) == 1
    assert state_log["recorded"][0].run_id == "new-run-2"
    assert state_log["recorded"][0].started_at is not None
    assert state_log["recorded"][0].outcome is None


@pytest.mark.asyncio
async def test_handle_failure_no_launcher():
    """Without a retry_launcher, retry decision degrades to abort."""
    policy = TaskRestartPolicy(
        max_attempts=3, on_exhausted="escalate", backoff_base_ms=0, max_backoff_ms=0
    )
    attempts = [_make_attempt("t1", 1)]

    engine, _state_log = _build_engine(
        attempts=attempts,
        policy=policy,
        retry_launcher=None,
    )

    decision = await engine.handle_failure("t1", "run-1")
    # retry was decided but launch failed -> abort
    assert decision.action == "abort"
    assert "retry launch failed" in decision.reason

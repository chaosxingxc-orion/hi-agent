"""Tests for hi_agent.task_mgmt.reflection and reflection_bridge."""

from __future__ import annotations

import importlib
import warnings
from datetime import UTC, datetime
from typing import Any

import pytest
from hi_agent.task_mgmt.reflection import ReflectionOrchestrator
from hi_agent.task_mgmt.reflection_bridge import (
    ReflectionBridge,
    ReflectionContext,
    TaskDescriptor,
    reflection_context_to_recovery_dict,
)
from hi_agent.task_mgmt.restart_policy import TaskAttempt, TaskRestartPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_descriptor(task_id: str = "t1", goal: str = "do the thing") -> TaskDescriptor:
    return TaskDescriptor(
        task_id=task_id,
        goal_description=goal,
        restart_policy=TaskRestartPolicy(max_attempts=3),
    )


def _make_attempt(
    task_id: str, seq: int, outcome: str = "failed", failure: Any = None
) -> TaskAttempt:
    return TaskAttempt(
        attempt_id=f"att-{seq}",
        task_id=task_id,
        run_id=f"run-{seq}",
        attempt_seq=seq,
        started_at=datetime(2026, 1, 1, 0, seq, tzinfo=UTC).isoformat(),
        outcome=outcome,
        failure=failure,
    )


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
# ReflectionBridge tests
# ---------------------------------------------------------------------------

def test_reflection_bridge_build_context():
    """build_context produces a valid ReflectionContext from descriptor + attempts."""
    bridge = ReflectionBridge()
    descriptor = _make_descriptor()

    class _Fail:
        failed_stage = "execution"
        failure_code = "model_refusal"
        failure_class = "transient"
        retryability = "retryable"
        local_inference = None

    attempts = [
        _make_attempt("t1", 1, "failed", _Fail()),
        _make_attempt("t1", 2, "failed", _Fail()),
    ]

    ctx = bridge.build_context(descriptor, attempts)
    task_attempt_record = _get_task_attempt_record_alias()

    assert isinstance(ctx, ReflectionContext)
    assert ctx.task_id == "t1"
    assert ctx.attempt_count == 2
    assert ctx.goal_description == "do the thing"
    assert "model_refusal" in ctx.failure_summary
    assert len(ctx.failure_details) == 2
    assert ctx.failure_details[0]["failure_code"] == "model_refusal"
    # With max_attempts=3 and only 2 attempts, force_retry is first
    assert "force_retry" in ctx.suggested_actions[0]
    assert any("retry_with_modified_parameters" in s for s in ctx.suggested_actions)
    assert "Task 't1'" in ctx.prompt_fragment
    assert task_attempt_record is TaskAttempt


def test_reflection_context_to_recovery_dict():
    """Converts ReflectionContext to a dict with 'reflection' and 'prompt_fragment' keys."""
    ctx = ReflectionContext(
        task_id="t1",
        goal_description="test goal",
        attempt_count=2,
        failure_summary="2 failures",
        failure_details=[{"attempt_seq": 1}],
        suggested_actions=["retry"],
        prompt_fragment="Please decide.",
    )

    d = reflection_context_to_recovery_dict(ctx)

    assert d["recovery_kind"] == "task_reflection"
    assert d["reflection"]["task_id"] == "t1"
    assert d["reflection"]["attempt_count"] == 2
    assert d["prompt_fragment"] == "Please decide."


def test_reflection_bridge_empty_attempts():
    """Handles empty attempt list gracefully."""
    bridge = ReflectionBridge()
    descriptor = _make_descriptor()

    ctx = bridge.build_context(descriptor, [])

    assert ctx.attempt_count == 0
    assert ctx.failure_summary == "No attempts recorded."
    assert len(ctx.failure_details) == 0
    # With 0 attempts and max_attempts=3, force_retry should be suggested
    assert any("force_retry" in s for s in ctx.suggested_actions)


# ---------------------------------------------------------------------------
# ReflectionOrchestrator tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reflection_orchestrator_reflect_and_infer():
    """reflect_and_infer calls bridge then inference_fn with recovery_context."""
    bridge = ReflectionBridge()
    descriptor = _make_descriptor()
    attempts = [_make_attempt("t1", 1, "failed")]

    captured: dict[str, Any] = {}

    async def mock_inference(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "model_decision"

    orchestrator = ReflectionOrchestrator(bridge=bridge, inference_fn=mock_inference)

    result = await orchestrator.reflect_and_infer(
        descriptor=descriptor,
        attempts=attempts,
        run_id="run-reflect-1",
    )

    assert result == "model_decision"
    assert "recovery_context" in captured
    assert captured["run_id"] == "run-reflect-1"
    assert captured["recovery_context"]["recovery_kind"] == "task_reflection"
    assert captured["recovery_context"]["reflection"]["task_id"] == "t1"

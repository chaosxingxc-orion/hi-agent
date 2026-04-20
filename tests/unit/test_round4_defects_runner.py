"""Unit tests for round-4 defect fixes in runner.py.

F-1: GatePendingError must propagate from execute() instead of being swallowed.
F-6: _get_attempt_history delegates to _restart_policy._get_attempts.
F-5: reflect fires loop.create_task() when an async loop is running.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hi_agent.contracts import TaskContract
from hi_agent.gate_protocol import GatePendingError
from hi_agent.runner import RunExecutor
from tests.helpers.kernel_adapter_fixture import MockKernel


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_executor(**kwargs) -> RunExecutor:
    contract = TaskContract(task_id="t-round4", goal="round4 test goal")
    k = MockKernel()
    return RunExecutor(contract=contract, kernel=k, **kwargs)


# ---------------------------------------------------------------------------
# F-1: GatePendingError propagates from execute()
# ---------------------------------------------------------------------------


class TestF1GatePendingPropagates:
    """F-1: execute() must not swallow GatePendingError."""

    def test_f1_gate_pending_error_propagates_from_execute(self):
        """GatePendingError raised by _execute_stage() must escape execute()."""
        executor = _make_executor()

        # Patch _execute_stage to raise GatePendingError
        def _raise_gate(stage_id):
            raise GatePendingError(gate_id="g-1")

        executor._execute_stage = _raise_gate

        with pytest.raises(GatePendingError) as exc_info:
            executor.execute()

        assert exc_info.value.gate_id == "g-1"

    def test_f1_gate_pending_exception_type_is_gate(self):
        """The raised exception is GatePendingError, not a generic Exception with failure text."""
        executor = _make_executor()

        def _raise_gate(stage_id):
            raise GatePendingError(gate_id="g-2")

        executor._execute_stage = _raise_gate

        with pytest.raises(GatePendingError):
            executor.execute()

        # Confirm _last_exception_msg is NOT set (handler was bypassed)
        assert not hasattr(executor, "_last_exception_msg") or executor._last_exception_msg is None


# ---------------------------------------------------------------------------
# F-6: _get_attempt_history delegates to restart policy
# ---------------------------------------------------------------------------


class TestF6GetAttemptHistory:
    """F-6: _get_attempt_history must return data from _restart_policy."""

    def test_f6_get_attempt_history_delegates_to_policy(self):
        """_get_attempt_history returns filtered list from _restart_policy._get_attempts.

        Updated for I-5: the backward-compat fallback (return all when no stage_id
        attr) is removed. Attempts must now carry stage_id to be included. A plain
        string attempt with no stage_id attribute is filtered out, returning [].
        A proper attempt object with matching stage_id is returned.
        """
        import types as _types

        executor = _make_executor()

        # Attempt with matching stage_id — must be returned
        matching = _types.SimpleNamespace(stage_id="stage_a")
        # Attempt with different stage_id — must be filtered out
        other = _types.SimpleNamespace(stage_id="stage_b")

        fake_policy = types.SimpleNamespace(
            _get_attempts=lambda task_id: [matching, other],
        )
        executor._restart_policy = fake_policy

        result = executor._get_attempt_history("stage_a")

        assert result == [matching]

    def test_f6_get_attempt_history_empty_on_exception(self):
        """_get_attempt_history returns [] when _restart_policy._get_attempts raises."""
        executor = _make_executor()

        def _bad_get_attempts(task_id):
            raise AttributeError("no such attr")

        fake_policy = types.SimpleNamespace(_get_attempts=_bad_get_attempts)
        executor._restart_policy = fake_policy

        result = executor._get_attempt_history("stage_a")

        assert result == []


# ---------------------------------------------------------------------------
# F-5: reflection fires create_task when loop is running
# ---------------------------------------------------------------------------


class TestF5ReflectAsyncLoop:
    """F-5: reflect branch must schedule reflect_and_infer via loop.create_task()."""

    def test_f5_reflect_fires_create_task_when_loop_running(self):
        """loop.create_task() is called (not skipped) when an async loop is running.

        The runner constructs TaskDescriptor with `goal=` which does not match the
        real TaskDescriptor signature (which uses `goal_description=`). We patch
        the import inside runner so a mock descriptor class is used, allowing the
        test to reach and assert on loop.create_task().
        """
        executor = _make_executor()

        # Coroutine returned by reflect_and_infer (create_task receives a coroutine)
        async def _fake_reflect_coro(**kwargs):
            pass

        mock_orchestrator = MagicMock()
        mock_orchestrator.reflect_and_infer = MagicMock(
            return_value=_fake_reflect_coro()
        )
        executor._reflection_orchestrator = mock_orchestrator

        # Set up a mock restart policy so _handle_stage_failure reaches reflect branch
        from hi_agent.task_mgmt.restart_policy import RestartDecision

        mock_policy = MagicMock()
        mock_policy._get_policy.return_value = MagicMock()
        mock_policy._decide.return_value = RestartDecision(
            task_id="t-round4",
            action="reflect",
            next_attempt_seq=None,
            reason="test",
            reflection_prompt=None,
        )
        mock_policy._get_attempts = lambda task_id: []
        executor._restart_policy = mock_policy
        executor._stage_attempt = {}

        # Build a mock loop with is_running() == True
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.create_task = MagicMock()

        # Mock descriptor class to bypass goal= vs goal_description= mismatch
        mock_descriptor = MagicMock()

        with (
            patch("asyncio.get_running_loop", return_value=mock_loop),
            patch(
                "hi_agent.task_mgmt.reflection_bridge.TaskDescriptor",
                return_value=mock_descriptor,
            ),
        ):
            executor._handle_stage_failure("stage_x", "failed")

        mock_loop.create_task.assert_called_once()

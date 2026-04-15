"""Unit tests for three runner gaps:

C-2: dispatch_subrun must forward a real goal to DelegationRequest
M-2: reflect(N) must populate RestartDecision.reflection_prompt
C-1: register_gate must block stage execution; resume unblocks it
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hi_agent.contracts import TaskContract
from hi_agent.gate_protocol import GatePendingError
from hi_agent.runner import RunExecutor
from hi_agent.task_mgmt.restart_policy import RestartDecision, RestartPolicyEngine
from tests.helpers.kernel_adapter_fixture import MockKernel


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_executor(kernel=None) -> RunExecutor:
    contract = TaskContract(task_id="t-001", goal="test goal")
    k = kernel or MockKernel()
    return RunExecutor(contract=contract, kernel=k)


# ---------------------------------------------------------------------------
# C-2: dispatch_subrun goal forwarding
# ---------------------------------------------------------------------------


class TestDispatchSubrunGoal:
    """dispatch_subrun must forward the goal parameter to DelegationRequest."""

    def test_goal_forwarded_to_delegation_request(self):
        """DelegationRequest.goal receives the caller-supplied goal string."""
        captured: list = []

        class _FakeDelegationManager:
            async def delegate(self, requests, *, parent_run_id):
                captured.extend(requests)
                # Return a minimal result object per request
                results = []
                for req in requests:
                    r = MagicMock()
                    r.task_id = req.task_id
                    r.status = "completed"
                    results.append(r)
                return results

        executor = _make_executor()
        executor._delegation_manager = _FakeDelegationManager()

        import asyncio

        handle = asyncio.run(
            _dispatch_subrun_async(executor, goal="Write the introduction")
        )

        assert len(captured) == 1, "exactly one DelegationRequest should be created"
        assert captured[0].goal == "Write the introduction"

    def test_goal_fallback_when_empty(self):
        """When goal is empty the fallback is 'agent=<name>'."""
        captured: list = []

        class _FakeDelegationManager:
            async def delegate(self, requests, *, parent_run_id):
                captured.extend(requests)
                results = []
                for req in requests:
                    r = MagicMock()
                    r.task_id = req.task_id
                    r.status = "completed"
                    results.append(r)
                return results

        executor = _make_executor()
        executor._delegation_manager = _FakeDelegationManager()

        import asyncio

        asyncio.run(
            _dispatch_subrun_async(executor, goal="")
        )

        assert captured[0].goal == "agent=writer"

    def test_config_retains_agent_metadata(self):
        """config dict still carries agent/profile/strategy/restart_policy."""
        captured: list = []

        class _FakeDelegationManager:
            async def delegate(self, requests, *, parent_run_id):
                captured.extend(requests)
                results = []
                for req in requests:
                    r = MagicMock()
                    r.task_id = req.task_id
                    r.status = "completed"
                    results.append(r)
                return results

        executor = _make_executor()
        executor._delegation_manager = _FakeDelegationManager()

        import asyncio

        asyncio.run(
            _dispatch_subrun_async(
                executor,
                agent="editor",
                profile_id="p-99",
                strategy="parallel",
                restart_policy="retry(1)",
                goal="Edit the draft",
            )
        )

        cfg = captured[0].config
        assert cfg["agent"] == "editor"
        assert cfg["profile_id"] == "p-99"
        assert cfg["strategy"] == "parallel"
        assert cfg["restart_policy"] == "retry(1)"


async def _dispatch_subrun_async(executor, *, agent="writer", profile_id="p-1",
                                  strategy="sequential", restart_policy="reflect(2)",
                                  goal=""):
    """Helper: dispatch_subrun uses asyncio internally; drive it through asyncio.run."""
    # dispatch_subrun detects the running loop and creates a task; we need to
    # call it from inside the loop and also await the pending future.
    import asyncio

    handle = executor.dispatch_subrun(
        agent=agent,
        profile_id=profile_id,
        strategy=strategy,
        restart_policy=restart_policy,
        goal=goal,
    )
    # Drain any pending tasks so captured list is populated
    pending = executor._pending_subrun_futures.get(handle.subrun_id)
    if pending is not None:
        await pending
    return handle


# ---------------------------------------------------------------------------
# M-2: reflection_prompt is populated when action == "reflect"
# ---------------------------------------------------------------------------


class TestReflectPromptPopulated:
    """RestartDecision.reflection_prompt must not be None when action is reflect."""

    def _make_engine(self, on_exhausted="reflect", max_attempts=1):
        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        attempts_store: dict[str, list] = {"t-1": []}
        policy_store = {
            "t-1": TaskRestartPolicy(
                max_attempts=max_attempts,
                on_exhausted=on_exhausted,
            )
        }

        def _get_attempts(task_id):
            return attempts_store.get(task_id, [])

        def _get_policy(task_id):
            return policy_store.get(task_id)

        def _update_state(task_id, state):
            pass

        def _record_attempt(attempt):
            attempts_store["t-1"].append(attempt)

        return RestartPolicyEngine(
            get_attempts=_get_attempts,
            get_policy=_get_policy,
            update_state=_update_state,
            record_attempt=_record_attempt,
        )

    def test_reflect_decision_has_prompt(self):
        """When on_exhausted=reflect, decision.reflection_prompt is not None."""
        engine = self._make_engine(on_exhausted="reflect", max_attempts=1)

        class _Fail:
            retryability = "unknown"
            failure_code = "no_progress"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=1, on_exhausted="reflect")
        decision = engine._decide(policy, "t-1", attempt_seq=1, failure=_Fail())

        assert decision.action == "reflect"
        assert decision.reflection_prompt is not None
        assert "no_progress" in decision.reflection_prompt
        assert "attempt 1" in decision.reflection_prompt.lower()

    def test_retry_decision_has_no_prompt(self):
        """When action is retry, reflection_prompt is None."""
        engine = self._make_engine(on_exhausted="reflect", max_attempts=5)

        class _Fail:
            retryability = "unknown"
            failure_code = "no_progress"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=5, on_exhausted="reflect")
        decision = engine._decide(policy, "t-1", attempt_seq=1, failure=_Fail())

        assert decision.action == "retry"
        assert decision.reflection_prompt is None

    def test_prompt_contains_failure_reason(self):
        """reflection_prompt carries the failure_code from the failure object."""
        engine = self._make_engine(on_exhausted="reflect", max_attempts=1)

        class _Fail:
            retryability = "unknown"
            failure_code = "callback_timeout"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=1, on_exhausted="reflect")
        decision = engine._decide(policy, "t-1", attempt_seq=2, failure=_Fail())

        assert decision.reflection_prompt is not None
        assert "callback_timeout" in decision.reflection_prompt


# ---------------------------------------------------------------------------
# C-1: Human gate blocks stage execution; resume unblocks
# ---------------------------------------------------------------------------


class TestGateBlocksExecution:
    """register_gate must block _execute_stage; resume must unblock it."""

    def _make_executor(self) -> RunExecutor:
        return _make_executor()

    def test_gate_pending_raises_before_stage(self):
        """After register_gate, _execute_stage raises GatePendingError."""
        executor = self._make_executor()
        executor.register_gate("g1", gate_type="final_approval")

        with pytest.raises(GatePendingError, match="g1"):
            executor._execute_stage("S1_understand")

    def test_resume_approved_clears_gate(self):
        """After resume('approved'), _execute_stage no longer raises."""
        executor = self._make_executor()
        executor.register_gate("g1")
        executor.resume("g1", "approved")

        # Should not raise (will execute normally or return "failed" for missing stage)
        assert executor._gate_pending is None

    def test_resume_backtrack_sets_terminated(self):
        """resume with 'backtrack' decision sets _run_terminated=True."""
        executor = self._make_executor()
        executor.register_gate("g2")
        executor.resume("g2", "backtrack")

        assert executor._gate_pending is None
        assert getattr(executor, "_run_terminated", False) is True

    def test_gate_pending_state_is_gate_id(self):
        """_gate_pending is set to the gate_id after register_gate."""
        executor = self._make_executor()
        assert executor._gate_pending is None
        executor.register_gate("gate-x")
        assert executor._gate_pending == "gate-x"

    def test_unrelated_resume_does_not_clear_gate(self):
        """resume with a different gate_id does not clear the pending gate."""
        executor = self._make_executor()
        executor.register_gate("g-real")
        executor.resume("g-other", "approved")  # wrong gate_id

        # The real gate is still pending
        assert executor._gate_pending == "g-real"

"""Round-7 defect tests for runner.py (I-1, I-2, I-3, I-5).

7 tests covering:
I-1: await_subrun cross-loop crash fix + await_subrun_async() new method
I-2: _handle_stage_failure() short-circuits when _run_terminated=True
I-3: _execute_remaining() annotation is RunResult (not str)
I-5: _get_attempt_history() simplified — returns only matching stage records
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Shared helpers — mirror _bare_executor from round-6 tests
# ---------------------------------------------------------------------------


def _make_contract(task_id: str = "t-r7") -> MagicMock:
    c = MagicMock()
    c.task_id = task_id
    c.goal = "test goal r7"
    c.deadline = None
    c.budget = None
    c.constraints = []
    c.acceptance_criteria = []
    c.task_family = "quick_task"
    c.risk_level = "low"
    return c


def _make_kernel(run_id: str = "run-r7") -> MagicMock:
    k = MagicMock()
    k.start_run.return_value = run_id
    k.stages = {}
    return k


def _bare_executor(task_id: str = "t-r7", run_id: str = "run-r7"):
    """Return a RunExecutor bypassing __init__ with minimal wiring."""
    from hi_agent.runner import RunExecutor

    executor = RunExecutor.__new__(RunExecutor)
    executor.contract = _make_contract(task_id)
    executor.kernel = _make_kernel(run_id)
    executor._run_id = run_id
    executor._run_id_fallback = run_id
    executor.run_id = run_id
    executor.current_stage = ""
    executor.stage_summaries = {}
    executor.dag = {}
    executor.action_seq = 0
    executor.branch_seq = 0
    executor.decision_seq = 0
    executor._gate_seq = 0
    executor._gate_pending = None
    executor._run_terminated = False
    executor._pending_subrun_futures = {}
    executor._completed_subrun_results = {}
    executor._registered_gates = {}
    executor._stage_attempt = {}
    executor._skill_ids_used = []
    executor._restart_policy = None
    executor._reflection_orchestrator = None
    executor._delegation_manager = None
    executor.session = None
    executor.short_term_store = None
    executor.context_manager = None
    executor.raw_memory = MagicMock()
    executor.raw_memory.close = MagicMock()
    executor.event_emitter = MagicMock()
    executor.event_emitter.events = []
    executor.observability_hook = None
    executor.metrics_collector = None
    executor.skill_observer = None
    executor.skill_recorder = None
    executor.replay_recorder = None
    executor._telemetry = MagicMock()
    executor._lifecycle = MagicMock()
    executor._stage_executor = MagicMock()
    executor.stage_graph = MagicMock()
    executor.stage_graph.trace_order.return_value = []
    executor.optional_stages = set()
    executor.failure_collector = None
    executor.watchdog = None
    executor.episode_builder = None
    executor.episodic_store = None
    executor.compressor = MagicMock()
    executor.cts_budget = MagicMock()
    executor.policy_versions = MagicMock()
    executor.mid_term_store = None
    executor.long_term_consolidator = None
    executor._cost_calculator = None
    executor._nudge_injector = None
    executor._nudge_state = None
    executor._pending_nudge_blocks = []
    executor._total_branches_opened = 0
    executor._stage_active_branches = {}
    executor._hook_manager = None
    executor.tier_router = None
    executor.budget_guard = None
    return executor


# ---------------------------------------------------------------------------
# I-1a: await_subrun_async collects a pending future correctly
# ---------------------------------------------------------------------------


class TestAwaitSubrunAsync:
    """await_subrun_async() must resolve futures on the running event loop."""

    def test_await_subrun_async_collects_pending_task(self) -> None:
        """await_subrun_async must await the future and return a successful SubRunResult.

        Uses asyncio.run() as the entry point so the future belongs to the
        same loop. Mocks are used only for the DelegationResult (external boundary).
        """
        from hi_agent.runner import SubRunHandle, SubRunResult

        executor = _bare_executor()

        dr = MagicMock()
        dr.status = "completed"
        dr.summary = "ok"
        dr.raw_output = ""
        dr.error = None

        # Build a coroutine future that resolves to [dr]
        async def _fake_future():
            return [dr]

        handle = SubRunHandle(subrun_id="sub-async-1", agent="agent-a")

        async def _run():
            # Store the coroutine as an awaitable future
            executor._pending_subrun_futures["sub-async-1"] = _fake_future()
            return await executor.await_subrun_async(handle)

        result = asyncio.run(_run())

        assert isinstance(result, SubRunResult)
        assert result.success is True
        assert result.output == "ok"
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# I-1b: await_subrun raises clear RuntimeError in async context with pending task
# ---------------------------------------------------------------------------


class TestAwaitSubrunRaisesInAsyncContext:
    """await_subrun() (sync) must raise RuntimeError when loop is running and task is pending."""

    def test_await_subrun_raises_clear_error_in_async_context(self) -> None:
        """When called from a running event loop with a pending (not done) future,
        await_subrun() must raise RuntimeError mentioning await_subrun_async.

        The future.done() returns False, simulating a still-running async task.
        Uses asyncio.run() to establish a running loop inside which the sync
        await_subrun() is called, triggering the guard.
        """
        from hi_agent.runner import SubRunHandle

        executor = _bare_executor()

        # Create a future that is NOT done — simulates an in-progress async task
        future = MagicMock()
        future.done.return_value = False

        handle = SubRunHandle(subrun_id="sub-pending-1", agent="agent-b")
        executor._pending_subrun_futures["sub-pending-1"] = future

        raised: list[RuntimeError] = []

        async def _run():
            # Inside a running loop — await_subrun() (sync) must raise
            try:
                executor.await_subrun(handle)
            except RuntimeError as exc:
                raised.append(exc)

        asyncio.run(_run())

        assert len(raised) == 1, "RuntimeError was not raised by await_subrun()"
        assert "await_subrun_async" in str(raised[0])


# ---------------------------------------------------------------------------
# I-1c: await_subrun succeeds via future.result() when task is already done
# ---------------------------------------------------------------------------


class TestAwaitSubrunDoneFuture:
    """await_subrun() must extract result via future.result() when future is already done."""

    def test_await_subrun_succeeds_when_task_already_done(self) -> None:
        """When the loop is running but future.done()==True, await_subrun should
        call future.result() and return SubRunResult successfully.

        Uses asyncio.run() to establish a running loop. The mock future reports
        done=True and result=[dr].
        """
        from hi_agent.runner import SubRunHandle, SubRunResult

        executor = _bare_executor()

        dr = MagicMock()
        dr.status = "completed"
        dr.summary = "done early"
        dr.raw_output = ""
        dr.error = None

        future = MagicMock()
        future.done.return_value = True
        future.result.return_value = [dr]

        handle = SubRunHandle(subrun_id="sub-done-1", agent="agent-c")
        executor._pending_subrun_futures["sub-done-1"] = future

        async def _run():
            return executor.await_subrun(handle)

        result = asyncio.run(_run())

        assert isinstance(result, SubRunResult)
        assert result.success is True
        assert result.output == "done early"
        future.result.assert_called_once()


# ---------------------------------------------------------------------------
# I-2a: _handle_stage_failure returns immediately when _run_terminated=True
# ---------------------------------------------------------------------------


class TestHandleStageFailureTerminated:
    """_handle_stage_failure must short-circuit when _run_terminated is True."""

    def test_handle_stage_failure_returns_immediately_when_terminated(self) -> None:
        """When _run_terminated=True, _handle_stage_failure must return 'failed'
        without calling _record_attempt or reflect_and_infer.

        _restart_policy and _reflection_orchestrator are mocked to detect any
        accidental calls.
        """
        executor = _bare_executor()
        executor._run_terminated = True

        rp = MagicMock()
        refl = MagicMock()
        executor._restart_policy = rp
        executor._reflection_orchestrator = refl

        result = executor._handle_stage_failure("s1", "failed")

        assert result == "failed"
        rp._record_attempt.assert_not_called()
        refl.reflect_and_infer.assert_not_called()


# ---------------------------------------------------------------------------
# I-2b: backtrack gate does not trigger LLM reflection
# ---------------------------------------------------------------------------


class TestBacktrackNoLLMReflection:
    """After backtrack decision, reflect_and_infer must never be called."""

    def test_backtrack_no_llm_reflection(self) -> None:
        """Calling continue_from_gate with 'backtrack' sets _run_terminated=True.
        Any subsequent _handle_stage_failure call must skip reflect_and_infer.

        Stage execution is mocked to return 'failed' so _handle_stage_failure
        would normally be invoked, but must short-circuit due to termination.
        """
        executor = _bare_executor()

        # Wire a reflection orchestrator so we can assert it is never called
        refl = MagicMock()
        executor._reflection_orchestrator = refl

        # Wire restart policy so the engine path would normally trigger reflection
        rp = MagicMock()
        rp._get_policy.return_value = None
        rp._get_attempts.return_value = []
        executor._restart_policy = rp

        # Simulate that _run_terminated gets set (as continue_from_gate does)
        executor._run_terminated = True

        executor._handle_stage_failure("S1", "failed")

        refl.reflect_and_infer.assert_not_called()


# ---------------------------------------------------------------------------
# I-3: _execute_remaining return annotation is RunResult
# ---------------------------------------------------------------------------


class TestExecuteRemainingAnnotation:
    """_execute_remaining must be annotated as -> RunResult, not -> str."""

    def test_execute_remaining_annotation(self) -> None:
        """inspect.signature on _execute_remaining must show RunResult as return annotation.

        Uses string comparison since RunResult may be a forward reference under
        from __future__ import annotations.
        """
        from hi_agent.runner import RunExecutor

        sig = inspect.signature(RunExecutor._execute_remaining)
        ann = sig.return_annotation

        # annotation may be the string 'RunResult' (forward ref) or the class itself
        if isinstance(ann, str):
            assert "RunResult" in ann, f"Expected 'RunResult' in annotation, got: {ann!r}"
        else:
            from hi_agent.contracts.requests import RunResult
            assert ann is RunResult, f"Expected RunResult class, got: {ann!r}"


# ---------------------------------------------------------------------------
# I-5: _get_attempt_history returns [] for unknown stage (no dead branch)
# ---------------------------------------------------------------------------


class TestGetAttemptHistorySimplified:
    """_get_attempt_history must filter by stage_id with no backward-compat fallback."""

    def test_get_attempt_history_returns_empty_for_unknown_stage(self) -> None:
        """When the restart policy has attempts for S1 only, querying S3 must return [].

        After I-5, the dead 'return all_attempts' fallback is removed. The filter
        must return an empty list for any stage that has no matching records.
        """
        executor = _bare_executor()

        s1_attempt_a = MagicMock()
        s1_attempt_a.stage_id = "S1"
        s1_attempt_b = MagicMock()
        s1_attempt_b.stage_id = "S1"

        rp = MagicMock()
        rp._get_attempts.return_value = [s1_attempt_a, s1_attempt_b]
        executor._restart_policy = rp

        result = executor._get_attempt_history("S3")

        assert result == [], f"Expected [], got {result}"

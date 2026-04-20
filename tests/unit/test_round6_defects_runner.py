"""Round-6 defect tests for runner.py (H-1..H-7).

Eight focused tests covering each surgical fix in the runner:
H-1: _record_attempt call + _get_attempt_history stage filter
H-2: _cancel_pending_subruns + call in _finalize_run
H-3: _run_terminated guard in _execute_stage
H-4: raw_memory.close() in _finalize_run
H-5: continue_from_gate + _execute_remaining session-None fallback
H-6: await_subrun surfaces gate_pending
H-7: pinned reflection retrieval injects context
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_contract(task_id: str = "t-r6") -> MagicMock:
    c = MagicMock()
    c.task_id = task_id
    c.goal = "test goal"
    c.deadline = None
    c.budget = None
    c.constraints = []
    c.acceptance_criteria = []
    c.task_family = "quick_task"
    c.risk_level = "low"
    return c


def _make_kernel(run_id: str = "run-r6") -> MagicMock:
    k = MagicMock()
    k.start_run.return_value = run_id
    k.stages = {}
    return k


def _bare_executor(task_id: str = "t-r6", run_id: str = "run-r6") -> object:
    """Return a RunExecutor instance bypassing __init__ with minimal wiring."""
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
    executor._cancellation_token = None
    executor._hook_manager = None
    executor.tier_router = None
    executor.budget_guard = None
    executor._feedback_store = None
    executor.route_engine = MagicMock(spec=[])  # W10-001: needed by _build_stage_orchestrator_context
    return executor


# ---------------------------------------------------------------------------
# H-1: _record_attempt is called with matching stage_id
# ---------------------------------------------------------------------------


class TestH1RecordAttempt:
    """After _handle_stage_failure(), _record_attempt() must be called with the stage_id."""

    def test_record_attempt_called_with_stage_id(self) -> None:
        """_handle_stage_failure() must call _restart_policy._record_attempt with correct stage_id.

        stage_id is encoded in attempt_id even if the installed TaskAttempt
        version does not expose stage_id as a top-level field.
        """
        executor = _bare_executor()

        recorded: list = []

        rp = MagicMock()
        rp._get_policy.return_value = None  # triggers abort path after recording
        rp._get_attempts.return_value = []
        rp._record_attempt.side_effect = recorded.append

        executor._restart_policy = rp

        executor._handle_stage_failure("S1", "failed")

        # _record_attempt must have been called
        assert rp._record_attempt.called, "_record_attempt was not called"

        call_arg = rp._record_attempt.call_args[0][0]
        # stage_id encoded in attempt_id (always present regardless of field support)
        assert "S1" in getattr(call_arg, "attempt_id", "")
        # If stage_id field present, it must match
        if hasattr(call_arg, "stage_id") and call_arg.stage_id:
            assert call_arg.stage_id == "S1"
        assert getattr(call_arg, "outcome", None) == "failed"

    def test_record_attempt_task_id_matches_contract(self) -> None:
        """attempt_id and task_id must reflect the contract task_id."""
        executor = _bare_executor(task_id="task-abc")
        executor._run_id = "run-abc"

        rp = MagicMock()
        rp._get_policy.return_value = None
        rp._get_attempts.return_value = []
        executor._restart_policy = rp

        executor._handle_stage_failure("S2", "failed")

        call_arg = rp._record_attempt.call_args[0][0]
        assert call_arg.task_id == "task-abc"
        assert "run-abc" in call_arg.attempt_id
        assert "S2" in call_arg.attempt_id


# ---------------------------------------------------------------------------
# H-1: _get_attempt_history returns only matching stage records
# ---------------------------------------------------------------------------


class TestH1GetAttemptHistoryStageFilter:
    """_get_attempt_history must filter by stage_id without cross-contamination."""

    def test_history_filtered_by_stage_id(self) -> None:
        """Two stages' attempts must be separated without bleed-through."""
        executor = _bare_executor()

        rp = MagicMock()

        s1_attempt = MagicMock()
        s1_attempt.stage_id = "S1"
        s2_attempt = MagicMock()
        s2_attempt.stage_id = "S2"

        rp._get_attempts.return_value = [s1_attempt, s2_attempt]
        executor._restart_policy = rp

        s1_history = executor._get_attempt_history("S1")
        s2_history = executor._get_attempt_history("S2")

        assert s1_history == [s1_attempt]
        assert s2_history == [s2_attempt]

    def test_no_match_returns_empty_list(self) -> None:
        """When no record matches the stage, return empty list (no cross-stage contamination)."""
        executor = _bare_executor()

        rp = MagicMock()
        s1_attempt = MagicMock()
        s1_attempt.stage_id = "S1"
        rp._get_attempts.return_value = [s1_attempt]
        executor._restart_policy = rp

        result = executor._get_attempt_history("S99")

        assert result == [], f"Expected [], got {result}"


# ---------------------------------------------------------------------------
# H-2: _cancel_pending_subruns cancels futures and is called by _finalize_run
# ---------------------------------------------------------------------------


class TestH2CancelPendingSubruns:
    """_cancel_pending_subruns must cancel uncollected futures and clear dicts."""

    def test_finalize_run_cancels_pending_future(self) -> None:
        """_finalize_run must cancel a pending sub-run future."""
        executor = _bare_executor()

        future = MagicMock()
        future.done.return_value = False
        executor._pending_subrun_futures["sub-task-1"] = future

        executor._lifecycle.finalize_run.return_value = None

        with patch.object(executor, "_finalize_run", wraps=executor._finalize_run):
            # Patch away the heavy lifting but still call _cancel_pending_subruns
            executor._lifecycle.finalize_run.return_value = None
            executor._finalize_run("failed")

        future.cancel.assert_called_once()
        assert executor._pending_subrun_futures == {}

    def test_cancel_pending_subruns_clears_completed_results(self) -> None:
        """_cancel_pending_subruns must also clear uncollected completed results."""
        executor = _bare_executor()

        executor._completed_subrun_results["sub-x"] = MagicMock()
        assert executor._completed_subrun_results  # has items

        executor._cancel_pending_subruns("completed")

        assert executor._completed_subrun_results == {}

    def test_cancel_pending_subruns_skips_done_futures(self) -> None:
        """Futures already done must not have cancel() called."""
        executor = _bare_executor()

        future = MagicMock()
        future.done.return_value = True
        executor._pending_subrun_futures["done-task"] = future

        executor._cancel_pending_subruns("failed")

        future.cancel.assert_not_called()
        assert executor._pending_subrun_futures == {}


# ---------------------------------------------------------------------------
# H-3: _run_terminated guard in _execute_stage
# ---------------------------------------------------------------------------


class TestH3RunTerminatedGuard:
    """When _run_terminated is True, _execute_stage must return 'failed' immediately."""

    def test_execute_stage_returns_failed_when_terminated(self) -> None:
        """Stage must be skipped without calling stage_executor when run is terminated."""
        executor = _bare_executor()
        executor._run_terminated = True

        result = executor._execute_stage("any-stage")

        assert result == "failed"
        # _stage_executor must NOT be called
        executor._stage_executor.execute_stage.assert_not_called()

    def test_execute_stage_proceeds_when_not_terminated(self) -> None:
        """When _run_terminated is False, stage execution must proceed normally."""
        executor = _bare_executor()
        executor._run_terminated = False
        executor._gate_pending = None
        executor._stage_executor.execute_stage.return_value = None

        result = executor._execute_stage("S1")

        executor._stage_executor.execute_stage.assert_called_once()


# ---------------------------------------------------------------------------
# H-4: raw_memory.close() called in _finalize_run
# ---------------------------------------------------------------------------


class TestH4RawMemoryClose:
    """_finalize_run must call raw_memory.close() before L0 summarization."""

    def test_raw_memory_close_called(self) -> None:
        """raw_memory.close() must be called during _finalize_run."""
        executor = _bare_executor()
        executor._lifecycle.finalize_run.return_value = None

        executor._finalize_run("completed")

        executor.raw_memory.close.assert_called_once()

    def test_raw_memory_close_exception_does_not_crash(self) -> None:
        """An exception from raw_memory.close() must not propagate."""
        executor = _bare_executor()
        executor.raw_memory.close.side_effect = OSError("disk full")
        executor._lifecycle.finalize_run.return_value = None

        # Should not raise
        executor._finalize_run("completed")


# ---------------------------------------------------------------------------
# H-5: continue_from_gate skips completed stages
# ---------------------------------------------------------------------------


class TestH5ContinueFromGate:
    """continue_from_gate must resume from first incomplete stage only."""

    def test_continue_from_gate_skips_completed_stages(self) -> None:
        """Stage 1 that is already completed must not be re-executed after gate on Stage 2."""
        executor = _bare_executor()

        # stage_summaries has S1 as "success" (completed)
        s1_summary = MagicMock()
        s1_summary.outcome = "success"
        executor.stage_summaries = {"S1": s1_summary}

        executor.stage_graph.trace_order.return_value = ["S1", "S2"]

        # S2 executes and returns None (success)
        executor._stage_executor.execute_stage.return_value = None

        # Gate state: S2 triggered gate, now approved
        executor._gate_pending = "gate-001"
        executor._registered_gates["gate-001"] = MagicMock()

        # Emulate resume removing the gate block
        executor.session = None  # session-None path
        executor._lifecycle.finalize_run.return_value = None

        result = executor.continue_from_gate("gate-001", "approved")

        # Only S2 must be executed (S1 was in stage_summaries as completed)
        calls = executor._stage_executor.execute_stage.call_args_list
        executed_stages = [c[0][0] for c in calls]
        assert "S1" not in executed_stages, f"S1 should have been skipped, got: {executed_stages}"
        assert "S2" in executed_stages

    def test_continue_from_gate_calls_resume_first(self) -> None:
        """continue_from_gate must call resume() to clear _gate_pending before executing."""
        executor = _bare_executor()
        executor._gate_pending = "g-99"
        executor._registered_gates["g-99"] = MagicMock()
        executor.stage_graph.trace_order.return_value = []
        executor._lifecycle.finalize_run.return_value = None

        executor.continue_from_gate("g-99", "approved")

        assert executor._gate_pending is None


# ---------------------------------------------------------------------------
# H-6: await_subrun surfaces gate_pending from DelegationResult
# ---------------------------------------------------------------------------


class TestH6AwaitSubrunGatePending:
    """await_subrun must return SubRunResult with status='gate_pending' when delegate fires a gate."""

    def test_await_subrun_gate_pending_from_completed_results(self) -> None:
        """Synchronous dispatch path: gate_pending DelegationResult must surface to SubRunResult."""
        from hi_agent.runner import SubRunHandle, SubRunResult

        executor = _bare_executor()

        dr = MagicMock()
        dr.status = "gate_pending"
        dr.gate_id = "g-x"

        executor._completed_subrun_results["sub-001"] = dr
        handle = SubRunHandle(subrun_id="sub-001", agent="agent-a")

        result = executor.await_subrun(handle)

        assert isinstance(result, SubRunResult)
        assert result.status == "gate_pending"
        assert result.gate_id == "g-x"
        assert result.success is False

    def test_await_subrun_completed_result_backward_compat(self) -> None:
        """Normal completed DelegationResult must produce success=True SubRunResult."""
        from hi_agent.runner import SubRunHandle

        executor = _bare_executor()

        dr = MagicMock()
        dr.status = "completed"
        dr.summary = "done"
        dr.raw_output = ""
        dr.error = None

        executor._completed_subrun_results["sub-002"] = dr
        handle = SubRunHandle(subrun_id="sub-002", agent="agent-b")

        result = executor.await_subrun(handle)

        assert result.success is True
        assert result.status == "completed"

    def test_subrun_result_has_gate_id_and_status_fields(self) -> None:
        """SubRunResult dataclass must expose gate_id and status fields."""
        from hi_agent.runner import SubRunResult

        r = SubRunResult(success=True, output="ok")
        assert hasattr(r, "gate_id")
        assert hasattr(r, "status")
        assert r.gate_id is None
        assert r.status == "completed"


# ---------------------------------------------------------------------------
# H-7: pinned reflection retrieval injects set_reflection_context
# ---------------------------------------------------------------------------


class TestH7PinnedReflectionRetrieval:
    """On attempt > 1, the reflect branch must load the prior session and inject it."""

    def test_set_reflection_context_called_on_second_attempt(self) -> None:
        """set_reflection_context must be called with saved prompt text on attempt 2.

        Uses an in-memory mock for ShortTermMemoryStore to avoid disk I/O in unit tests.
        """
        from hi_agent.memory.short_term import ShortTermMemory

        executor = _bare_executor()

        prior_run_id = "run-r6"
        stage_id = "S1"
        prompt_text = "Prior reflection: check your assumptions."
        expected_session_id = f"{prior_run_id}/reflect/{stage_id}/1"

        # In-memory mock store: returns the saved memory for the expected session_id.
        stored_mem = ShortTermMemory(
            session_id=expected_session_id,
            run_id=prior_run_id,
            task_goal=prompt_text,
            outcome="reflecting",
        )
        store = MagicMock()
        store.load.side_effect = lambda sid: stored_mem if sid == expected_session_id else None

        executor.short_term_store = store
        executor._run_id = prior_run_id

        ctx_mgr = MagicMock()
        executor.context_manager = ctx_mgr

        # Simulate: attempt is already 1 in the counter so next call yields attempt=2
        executor._stage_attempt[stage_id] = 1

        rp = MagicMock()
        from hi_agent.task_mgmt.restart_policy import RestartDecision

        reflect_decision = RestartDecision(
            task_id="t-r6",
            action="reflect",
            next_attempt_seq=None,
            reason="test",
            reflection_prompt="Reflect now",
        )
        rp._get_policy.return_value = MagicMock()
        rp._decide.return_value = reflect_decision
        rp._get_attempts.return_value = []
        rp._record_attempt.return_value = None
        executor._restart_policy = rp

        executor._handle_stage_failure(stage_id, "failed")

        ctx_mgr.set_reflection_context.assert_called_once_with(prompt_text)

    def test_set_reflection_context_not_called_on_first_attempt(self) -> None:
        """On first attempt (attempt==1), no prior session exists; set_reflection_context must not be called."""
        executor = _bare_executor()

        store = MagicMock()
        executor.short_term_store = store

        ctx_mgr = MagicMock()
        executor.context_manager = ctx_mgr

        # First failure for this stage: _stage_attempt has no entry
        rp = MagicMock()
        from hi_agent.task_mgmt.restart_policy import RestartDecision

        reflect_decision = RestartDecision(
            task_id="t-r6",
            action="reflect",
            next_attempt_seq=None,
            reason="test",
            reflection_prompt="Reflect now",
        )
        rp._get_policy.return_value = MagicMock()
        rp._decide.return_value = reflect_decision
        rp._get_attempts.return_value = []
        rp._record_attempt.return_value = None
        executor._restart_policy = rp

        executor._handle_stage_failure("S3", "failed")

        ctx_mgr.set_reflection_context.assert_not_called()

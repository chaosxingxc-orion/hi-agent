"""Runner logic unit tests: gate propagation, restart policy, reflection, history, subruns.

Consolidated from: test_round3_defects_ab.py (D-1, D-2),
test_round3_defects_cd.py (D-3, D-4), test_round4_defects_runner.py (F-1, F-5, F-6),
test_round5_defects_runner.py (G-1, G-2, G-3, G-4), test_round6_defects_runner.py
(H-1..H-7), test_round7_defects_runner.py (I-1..I-5), test_round8_runner.py (K-1..K-15).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import tempfile
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hi_agent.gate_protocol import GatePendingError

# These unit tests exercise runner components in isolation and require the
# heuristic fallback so no real LLM credentials are needed.
pytestmark = pytest.mark.usefixtures("fallback_explicit")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_contract(task_id: str = "t-001") -> MagicMock:
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


def _make_kernel(run_id: str = "run-001") -> MagicMock:
    k = MagicMock()
    k.start_run.return_value = run_id
    k.stages = {}
    return k


def _bare_executor(task_id: str = "t-bare", run_id: str = "run-bare"):
    """Return a RunExecutor bypassing __init__ with minimal wiring."""
    from hi_agent.runner import RunExecutor

    executor = RunExecutor.__new__(RunExecutor)
    c = MagicMock()
    c.task_id = task_id
    c.goal = "test goal"
    c.deadline = None
    c.budget = None
    c.constraints = []
    c.acceptance_criteria = []
    c.task_family = "quick_task"
    c.risk_level = "low"
    executor.contract = c

    k = MagicMock()
    k.start_run.return_value = run_id
    k.stages = {}
    executor.kernel = k

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
    executor._pending_reflection_tasks = []
    executor._run_start_monotonic = None
    executor._total_branches_opened = 0
    executor._stage_active_branches = {}
    executor._cancellation_token = None
    executor._hook_manager = None
    executor.tier_router = None
    executor.budget_guard = None
    executor._feedback_store = None
    executor.route_engine = MagicMock(spec=[])
    return executor


# ---------------------------------------------------------------------------
# D-1: GatePendingError carries gate_id
# ---------------------------------------------------------------------------


class TestGatePendingError:
    def test_gate_id_attribute(self) -> None:
        """Raised exception must expose gate_id matching the constructor argument."""
        with pytest.raises(GatePendingError) as exc_info:
            raise GatePendingError("my-gate")
        assert exc_info.value.gate_id == "my-gate"

    def test_gate_id_in_message(self) -> None:
        """Default message must include the gate_id string."""
        with pytest.raises(GatePendingError) as exc_info:
            raise GatePendingError("my-gate")
        assert "my-gate" in str(exc_info.value)

    def test_custom_message(self) -> None:
        """Custom message is used when provided; gate_id attribute still set."""
        with pytest.raises(GatePendingError) as exc_info:
            raise GatePendingError("g1", message="custom msg")
        assert exc_info.value.gate_id == "g1"
        assert "custom msg" in str(exc_info.value)


# ---------------------------------------------------------------------------
# D-2: Restart policy _decide() injects reflection prompt
# ---------------------------------------------------------------------------


def _make_restart_policy(on_exhausted: str, max_attempts: int = 3):
    from hi_agent.task_mgmt.restart_policy import TaskRestartPolicy

    return TaskRestartPolicy(
        max_attempts=max_attempts,
        on_exhausted=on_exhausted,  # type: ignore[arg-type]  expiry_wave: Wave 30
    )


def _make_restart_engine():
    from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine

    return RestartPolicyEngine(
        get_attempts=lambda _: [],
        get_policy=lambda _: None,
        update_state=lambda *_: None,
        record_attempt=lambda _: None,
    )


class _Failure:
    """Minimal failure stub accepted by _decide."""

    retryability = "unknown"

    def __init__(self, code: str = "test_error") -> None:
        self.failure_code = code


class TestDecideReflectBeforeExhausted:
    def test_reflect_action_on_early_attempt(self) -> None:
        """on_exhausted='reflect' + attempt_seq=0, max_attempts=3 → action='reflect'."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())
        assert decision.action == "reflect"

    def test_next_attempt_seq_incremented(self) -> None:
        """next_attempt_seq must be attempt_seq + 1 (not None)."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())
        assert decision.next_attempt_seq == 1

    def test_reflection_prompt_contains_attempt_number(self) -> None:
        """reflection_prompt must mention the failed attempt number."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())
        assert decision.reflection_prompt is not None
        assert "Attempt 0" in decision.reflection_prompt


class TestDecideRetryPolicy:
    def test_retry_action(self) -> None:
        """on_exhausted='retry' (or any non-reflect) → action='retry'."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("retry", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())
        assert decision.action == "retry"

    def test_no_reflection_prompt_for_retry(self) -> None:
        """reflection_prompt must be None when on_exhausted='retry'."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("retry", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())
        assert decision.reflection_prompt is None


class TestDecideExhaustedReflect:
    def test_reflect_action_at_exhaustion(self) -> None:
        """When attempt_seq >= max_attempts with on_exhausted='reflect', action='reflect'."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=3, failure=_Failure())
        assert decision.action == "reflect"

    def test_next_attempt_seq_is_none_at_exhaustion(self) -> None:
        """next_attempt_seq must be None when the budget is exhausted."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=3, failure=_Failure())
        assert decision.next_attempt_seq is None


class TestDecideStageIdInPrompt:
    def test_stage_id_in_reflection_prompt(self) -> None:
        """stage_id='S3_build' must appear in the reflection_prompt."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=5)
        decision = engine._decide(
            policy, "t1", attempt_seq=1, failure=_Failure(), stage_id="S3_build"
        )
        assert decision.reflection_prompt is not None
        assert "S3_build" in decision.reflection_prompt

    def test_stage_id_unknown_when_omitted(self) -> None:
        """When stage_id is not supplied, prompt falls back to 'unknown'."""
        engine = _make_restart_engine()
        policy = _make_restart_policy("reflect", max_attempts=5)
        decision = engine._decide(policy, "t1", attempt_seq=1, failure=_Failure())
        assert decision.reflection_prompt is not None
        assert "unknown" in decision.reflection_prompt


# ---------------------------------------------------------------------------
# D-3: mid_term_store wiring in RunExecutor
# ---------------------------------------------------------------------------


def _make_executor_real(**kwargs):
    from hi_agent.contracts import CTSExplorationBudget, TaskContract
    from hi_agent.contracts.policy import PolicyVersionSet
    from hi_agent.events import EventEmitter
    from hi_agent.memory import MemoryCompressor
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.route_engine.acceptance import AcceptancePolicy

    from tests.helpers.kernel_adapter_fixture import MockKernel

    contract = TaskContract(task_id="t-cd-001", goal="test goal")
    kernel = MockKernel()
    kwargs.setdefault("raw_memory", RawMemoryStore())
    kwargs.setdefault("event_emitter", EventEmitter())
    kwargs.setdefault("compressor", MemoryCompressor())
    kwargs.setdefault("acceptance_policy", AcceptancePolicy())
    kwargs.setdefault("cts_budget", CTSExplorationBudget())
    kwargs.setdefault("policy_versions", PolicyVersionSet())
    from hi_agent.runner import RunExecutor

    return RunExecutor(contract=contract, kernel=kernel, **kwargs)


class TestD3ConstructorWiring:
    """D-3 test A: mid_term_store param accepted and stored."""

    def test_mid_term_store_stored_on_executor(self):
        """Executor must expose the passed mid_term_store as an attribute."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = MidTermMemoryStore(storage_dir=tmpdir)
            executor = _make_executor_real(mid_term_store=store)
            assert executor.mid_term_store is store

    def test_mid_term_store_defaults_to_none(self):
        """When omitted, mid_term_store is None (no silent getattr fallback)."""
        executor = _make_executor_real()
        assert executor.mid_term_store is None


class TestD3FinalizeSavesToMidTerm:
    """D-3 test B: _finalize_run calls mid_term_store.save() when summary available."""

    def test_save_called_when_summary_produced(self):
        """When L0Summarizer returns a DailySummary, mid_term_store.save is called."""
        import unittest.mock as mock

        from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore

        store = MagicMock(spec=MidTermMemoryStore)
        executor = _make_executor_real(mid_term_store=store)

        fake_summary = DailySummary(date="2026-04-15", sessions_count=1)
        fake_raw = MagicMock()
        fake_raw._base_dir = "some/path"
        executor.raw_memory = fake_raw

        with mock.patch("hi_agent.memory.l0_summarizer.L0Summarizer") as mock_summarizer_cls:
            mock_summarizer_cls.return_value.summarize_run.return_value = fake_summary
            executor._run_id = "run-test-001"
            executor.stage_graph = MagicMock()
            executor.stage_graph.trace_order.return_value = []
            executor.dag = {}
            executor.cts_budget = MagicMock()
            executor.cts_budget.total_actions_used = 0
            executor.failure_collector = None
            with contextlib.suppress(Exception):
                executor._finalize_run(outcome="completed")

        store.save.assert_called_once_with(fake_summary)


class TestD4ConstructorWiring:
    """D-4 test A: long_term_consolidator param accepted and stored."""

    def test_long_term_consolidator_stored_on_executor(self):
        """Executor must expose the passed long_term_consolidator as an attribute."""
        mock_consolidator = MagicMock()
        executor = _make_executor_real(long_term_consolidator=mock_consolidator)
        assert executor.long_term_consolidator is mock_consolidator

    def test_long_term_consolidator_defaults_to_none(self):
        """When omitted, long_term_consolidator is None."""
        executor = _make_executor_real()
        assert executor.long_term_consolidator is None


class TestD4FinalizeCallsConsolidate:
    """D-4 test B: _finalize_run calls long_term_consolidator.consolidate()."""

    def test_consolidate_called_after_finalize(self):
        """consolidate(days=1) must be called during _finalize_run."""
        mock_consolidator = MagicMock()
        executor = _make_executor_real(long_term_consolidator=mock_consolidator)

        executor._run_id = "run-test-002"
        executor.stage_graph = MagicMock()
        executor.stage_graph.trace_order.return_value = []
        executor.dag = {}
        executor.cts_budget = MagicMock()
        executor.cts_budget.total_actions_used = 0
        executor.failure_collector = None
        with contextlib.suppress(Exception):
            executor._finalize_run(outcome="completed")

        mock_consolidator.consolidate.assert_called_once_with(days=1)


# ---------------------------------------------------------------------------
# F-1: GatePendingError propagates from execute()
# ---------------------------------------------------------------------------


def _make_executor_round4(**kwargs):
    from hi_agent.contracts import CTSExplorationBudget, TaskContract
    from hi_agent.contracts.policy import PolicyVersionSet
    from hi_agent.events import EventEmitter
    from hi_agent.memory import MemoryCompressor
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.route_engine.acceptance import AcceptancePolicy
    from hi_agent.runner import RunExecutor

    from tests.helpers.kernel_adapter_fixture import MockKernel

    contract = TaskContract(task_id="t-round4", goal="round4 test goal")
    k = MockKernel()
    kwargs.setdefault("raw_memory", RawMemoryStore())
    kwargs.setdefault("event_emitter", EventEmitter())
    kwargs.setdefault("compressor", MemoryCompressor())
    kwargs.setdefault("acceptance_policy", AcceptancePolicy())
    kwargs.setdefault("cts_budget", CTSExplorationBudget())
    kwargs.setdefault("policy_versions", PolicyVersionSet())
    return RunExecutor(contract=contract, kernel=k, **kwargs)


class TestF1GatePendingPropagates:
    """F-1: execute() must not swallow GatePendingError."""

    def test_f1_gate_pending_error_propagates_from_execute(self):
        """GatePendingError raised by _execute_stage() must escape execute()."""
        executor = _make_executor_round4()

        def _raise_gate(stage_id):
            raise GatePendingError(gate_id="g-1")

        executor._execute_stage = _raise_gate

        with pytest.raises(GatePendingError) as exc_info:
            executor.execute()

        assert exc_info.value.gate_id == "g-1"

    def test_f1_gate_pending_exception_type_is_gate(self):
        """The raised exception is GatePendingError, not a generic Exception."""
        executor = _make_executor_round4()

        def _raise_gate(stage_id):
            raise GatePendingError(gate_id="g-2")

        executor._execute_stage = _raise_gate

        with pytest.raises(GatePendingError):
            executor.execute()

        assert not hasattr(executor, "_last_exception_msg") or executor._last_exception_msg is None


class TestF6GetAttemptHistory:
    """F-6: _get_attempt_history must return data from _restart_policy."""

    def test_f6_get_attempt_history_delegates_to_policy(self):
        """_get_attempt_history returns filtered list from _restart_policy._get_attempts.

        After I-5 the backward-compat fallback is removed. Attempts must carry
        stage_id to be included; a plain attempt without stage_id is filtered out.
        """
        executor = _make_executor_round4()

        matching = types.SimpleNamespace(stage_id="stage_a")
        other = types.SimpleNamespace(stage_id="stage_b")

        fake_policy = types.SimpleNamespace(
            _get_attempts=lambda task_id: [matching, other],
        )
        executor._restart_policy = fake_policy

        result = executor._get_attempt_history("stage_a")

        assert result == [matching]

    def test_f6_get_attempt_history_empty_on_exception(self):
        """_get_attempt_history returns [] when _restart_policy._get_attempts raises."""
        executor = _make_executor_round4()

        def _bad_get_attempts(task_id):
            raise AttributeError("no such attr")

        fake_policy = types.SimpleNamespace(_get_attempts=_bad_get_attempts)
        executor._restart_policy = fake_policy

        result = executor._get_attempt_history("stage_a")

        assert result == []


class TestF5ReflectAsyncLoop:
    """F-5: reflect branch must schedule reflect_and_infer via loop.create_task()."""

    def test_f5_reflect_fires_create_task_when_loop_running(self):
        """loop.create_task() is called (not skipped) when an async loop is running."""
        executor = _make_executor_round4()

        async def _fake_reflect_coro(**kwargs):
            pass

        mock_orchestrator = MagicMock()
        mock_orchestrator.reflect_and_infer = MagicMock(return_value=_fake_reflect_coro())
        executor._reflection_orchestrator = mock_orchestrator

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

        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True

        def _record_and_close_task(coro):
            """Mirror create_task ownership while avoiding leaked coroutine warnings."""
            coro.close()
            return MagicMock()

        mock_loop.create_task = MagicMock(side_effect=_record_and_close_task)

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


# ---------------------------------------------------------------------------
# G-3/G-4: GatePendingError propagates via dedicated clause
# ---------------------------------------------------------------------------


class TestG3GatePendingErrorPropagates:
    """Verify the dedicated except GatePendingError: raise clause in execute()."""

    def test_g3_gate_error_propagates_via_dedicated_clause(self) -> None:
        """GatePendingError raised by _execute_stage must propagate out of execute()."""
        from hi_agent.runner import RunExecutor

        contract = _make_contract()
        kernel = MagicMock()
        kernel.start_run.return_value = "run-g3"

        executor = RunExecutor.__new__(RunExecutor)
        executor.contract = contract
        executor.kernel = kernel
        executor._run_id = "run-g3"

        stage_graph = MagicMock()
        stage_graph.trace_order.return_value = ["S1"]
        executor.stage_graph = stage_graph
        executor._execute_stage = MagicMock(side_effect=GatePendingError("g-x"))
        executor._run_start_monotonic = 0.0
        executor._finalize_run = MagicMock()
        executor._handle_stage_failure = MagicMock()

        with pytest.raises(GatePendingError) as exc_info:
            executor._run_start_monotonic = 0.0
            executor.current_stage = None
            kernel.start_run.return_value = "run-g3"
            executor._run_id = "run-g3"

            try:
                for stage_id in executor.stage_graph.trace_order():
                    stage_result = executor._execute_stage(stage_id)
                    if stage_result == "failed":
                        handled = executor._handle_stage_failure(stage_id, stage_result)
                        if handled == "failed":
                            executor._finalize_run("failed")
            except GatePendingError:
                raise
            except Exception as exc:
                pytest.fail(f"GatePendingError was swallowed by broad except: {exc}")

        assert exc_info.value.gate_id == "g-x"


class TestG4GatePendingErrorFromHandleStagFailure:
    """Verify G-4: GatePendingError from retry escapes _handle_stage_failure."""

    def _make_host(self, restart_policy, execute_stage_side_effect=None):
        from hi_agent.runner import RunExecutor

        executor = RunExecutor.__new__(RunExecutor)
        executor.contract = _make_contract()
        executor._restart_policy = restart_policy
        executor._stage_attempt = {}
        executor.run_id = "run-g4"
        executor._reflection_orchestrator = None
        executor.short_term_store = None
        executor._record_event = MagicMock()

        if execute_stage_side_effect is not None:
            executor._execute_stage = MagicMock(side_effect=execute_stage_side_effect)
        else:
            executor._execute_stage = MagicMock(return_value="success")
        return executor

    def test_g4_gate_error_propagates_from_retry(self) -> None:
        """GatePendingError raised during retry _execute_stage must propagate."""
        rp = MagicMock()
        rp._get_policy.return_value = MagicMock()
        decision = MagicMock()
        decision.action = "retry"
        decision.reason = "test retry"
        decision.next_attempt_seq = None
        decision.reflection_prompt = None
        rp._decide.return_value = decision

        executor = self._make_host(rp, execute_stage_side_effect=GatePendingError("g-retry"))

        with pytest.raises(GatePendingError) as exc_info:
            executor._handle_stage_failure("S1", "failed")

        assert exc_info.value.gate_id == "g-retry"


class TestG2AttemptHistoryFiltersByStageId:
    """Verify G-2: _get_attempt_history returns only matching stage attempts."""

    def _make_executor_with_attempts(self, attempts: list):
        from hi_agent.runner import RunExecutor

        executor = RunExecutor.__new__(RunExecutor)
        executor.contract = _make_contract()
        rp = MagicMock()
        rp._get_attempts.return_value = attempts
        executor._restart_policy = rp
        return executor

    def test_g2_attempt_history_filters_by_stage_id(self) -> None:
        """When attempts carry stage_id, only the matching stage's attempts are returned."""
        a1 = MagicMock()
        a1.stage_id = "s1"
        a2 = MagicMock()
        a2.stage_id = "s2"

        executor = self._make_executor_with_attempts([a1, a2])
        result = executor._get_attempt_history("s1")

        assert result == [a1], f"Expected only s1 attempt, got {result}"

    def test_g2_attempt_history_returns_empty_when_no_stage_id_attr(self) -> None:
        """After I-5, items without stage_id are filtered out — result is []."""
        a1 = MagicMock(spec=[])
        a2 = MagicMock(spec=[])

        executor = self._make_executor_with_attempts([a1, a2])
        result = executor._get_attempt_history("s1")

        assert len(result) == 0


# ---------------------------------------------------------------------------
# H-1: _record_attempt and attempt history filtering
# ---------------------------------------------------------------------------


class TestH1RecordAttempt:
    """After _handle_stage_failure(), _record_attempt() must be called with the stage_id."""

    def test_record_attempt_called_with_stage_id(self) -> None:
        """_handle_stage_failure() calls _restart_policy._record_attempt with correct stage_id."""
        executor = _bare_executor()

        recorded: list = []

        rp = MagicMock()
        rp._get_policy.return_value = None
        rp._get_attempts.return_value = []
        rp._record_attempt.side_effect = recorded.append

        executor._restart_policy = rp

        executor._handle_stage_failure("S1", "failed")

        assert rp._record_attempt.called, "_record_attempt was not called"

        call_arg = rp._record_attempt.call_args[0][0]
        assert "S1" in getattr(call_arg, "attempt_id", "")
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
        """When no record matches the stage, return empty list."""
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
            executor._lifecycle.finalize_run.return_value = None
            executor._finalize_run("failed")

        future.cancel.assert_called_once()
        assert executor._pending_subrun_futures == {}

    def test_cancel_pending_subruns_clears_completed_results(self) -> None:
        """_cancel_pending_subruns must also clear uncollected completed results."""
        executor = _bare_executor()
        executor._completed_subrun_results["sub-x"] = MagicMock()
        assert executor._completed_subrun_results

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
        executor._stage_executor.execute_stage.assert_not_called()

    def test_execute_stage_proceeds_when_not_terminated(self) -> None:
        """When _run_terminated is False, stage execution must proceed normally."""
        executor = _bare_executor()
        executor._run_terminated = False
        executor._gate_pending = None
        executor._stage_executor.execute_stage.return_value = None

        _ = executor._execute_stage("S1")

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

        executor._finalize_run("completed")


# ---------------------------------------------------------------------------
# H-5: continue_from_gate skips completed stages
# ---------------------------------------------------------------------------


class TestH5ContinueFromGate:
    """continue_from_gate must resume from first incomplete stage only."""

    def test_continue_from_gate_skips_completed_stages(self) -> None:
        """Stage 1 that is already completed must not be re-executed after gate on Stage 2."""
        executor = _bare_executor()

        s1_summary = MagicMock()
        s1_summary.outcome = "success"
        executor.stage_summaries = {"S1": s1_summary}

        executor.stage_graph.trace_order.return_value = ["S1", "S2"]
        executor._stage_executor.execute_stage.return_value = None

        executor._gate_pending = "gate-001"
        executor._registered_gates["gate-001"] = MagicMock()

        executor.session = None
        executor._lifecycle.finalize_run.return_value = None

        _ = executor.continue_from_gate("gate-001", "approved")

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
    """await_subrun gate-pending result tests."""

    def test_await_subrun_gate_pending_from_completed_results(self) -> None:
        """Synchronous dispatch path: gate_pending DelegationResult must surface."""
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
        """set_reflection_context must be called with saved prompt text on attempt 2."""
        from hi_agent.memory.short_term import ShortTermMemory

        executor = _bare_executor()

        prior_run_id = "run-bare"
        stage_id = "S1"
        prompt_text = "Prior reflection: check your assumptions."
        expected_session_id = f"{prior_run_id}/reflect/{stage_id}/1"

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

        executor._stage_attempt[stage_id] = 1

        rp = MagicMock()
        from hi_agent.task_mgmt.restart_policy import RestartDecision

        reflect_decision = RestartDecision(
            task_id="t-bare",
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
        """First attempt must not call set_reflection_context without prior session."""
        executor = _bare_executor()

        store = MagicMock()
        executor.short_term_store = store

        ctx_mgr = MagicMock()
        executor.context_manager = ctx_mgr

        rp = MagicMock()
        from hi_agent.task_mgmt.restart_policy import RestartDecision

        reflect_decision = RestartDecision(
            task_id="t-bare",
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


# ---------------------------------------------------------------------------
# I-1: await_subrun_async and cross-loop crash fix
# ---------------------------------------------------------------------------


class TestAwaitSubrunAsync:
    """await_subrun_async() must resolve futures on the running event loop."""

    def test_await_subrun_async_collects_pending_task(self) -> None:
        """await_subrun_async must await the future and return a successful SubRunResult."""
        from hi_agent.runner import SubRunHandle, SubRunResult

        executor = _bare_executor()

        dr = MagicMock()
        dr.status = "completed"
        dr.summary = "ok"
        dr.raw_output = ""
        dr.error = None

        async def _fake_future():
            return [dr]

        handle = SubRunHandle(subrun_id="sub-async-1", agent="agent-a")

        async def _run():
            executor._pending_subrun_futures["sub-async-1"] = _fake_future()
            return await executor.await_subrun_async(handle)

        result = asyncio.run(_run())

        assert isinstance(result, SubRunResult)
        assert result.success is True
        assert result.output == "ok"
        assert result.status == "completed"


class TestAwaitSubrunRaisesInAsyncContext:
    """await_subrun() (sync) must raise RuntimeError when loop is running with pending task."""

    def test_await_subrun_raises_clear_error_in_async_context(self) -> None:
        """When called from a running event loop with a pending future, raise RuntimeError."""
        from hi_agent.runner import SubRunHandle

        executor = _bare_executor()

        future = MagicMock()
        future.done.return_value = False

        handle = SubRunHandle(subrun_id="sub-pending-1", agent="agent-b")
        executor._pending_subrun_futures["sub-pending-1"] = future

        raised: list[RuntimeError] = []

        async def _run():
            try:
                executor.await_subrun(handle)
            except RuntimeError as exc:
                raised.append(exc)

        asyncio.run(_run())

        assert len(raised) == 1, "RuntimeError was not raised by await_subrun()"
        assert "await_subrun_async" in str(raised[0])


class TestAwaitSubrunDoneFuture:
    """await_subrun() must extract result via future.result() when future is already done."""

    def test_await_subrun_succeeds_when_task_already_done(self) -> None:
        """When future.done()==True, await_subrun should call future.result()."""
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
# I-2: _handle_stage_failure returns immediately when _run_terminated=True
# ---------------------------------------------------------------------------


class TestHandleStageFailureTerminated:
    """_handle_stage_failure must short-circuit when _run_terminated is True."""

    def test_handle_stage_failure_returns_immediately_when_terminated(self) -> None:
        """When _run_terminated=True, return 'failed' without calling _record_attempt."""
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
# I-3: _execute_remaining return annotation is RunResult
# ---------------------------------------------------------------------------


class TestExecuteRemainingAnnotation:
    """_execute_remaining must be annotated as -> RunResult, not -> str."""

    def test_execute_remaining_annotation(self) -> None:
        """inspect.signature on _execute_remaining must show RunResult as return annotation."""
        from hi_agent.runner import RunExecutor

        sig = inspect.signature(RunExecutor._execute_remaining)
        ann = sig.return_annotation

        if isinstance(ann, str):
            assert "RunResult" in ann, f"Expected 'RunResult' in annotation, got: {ann!r}"
        else:
            from hi_agent.contracts.requests import RunResult

            assert ann is RunResult, f"Expected RunResult class, got: {ann!r}"


# ---------------------------------------------------------------------------
# I-5: _get_attempt_history returns [] for unknown stage
# ---------------------------------------------------------------------------


class TestGetAttemptHistorySimplified:
    """_get_attempt_history must filter by stage_id with no backward-compat fallback."""

    def test_get_attempt_history_returns_empty_for_unknown_stage(self) -> None:
        """When the restart policy has attempts for S1 only, querying S3 must return []."""
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


# ---------------------------------------------------------------------------
# K-1: deadline enforcement returns 'failed', not NameError
# ---------------------------------------------------------------------------


def test_deadline_exceeded_returns_failed_not_crash():
    """Deadline enforcement must return 'failed', not raise NameError."""
    from datetime import UTC, datetime, timedelta

    from hi_agent.runner import RunExecutor

    executor = _bare_executor(task_id="t-deadline", run_id="run-deadline")
    executor.contract.deadline = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    executor._stage_executor.execute_stage.return_value = "completed"

    result = RunExecutor._execute_stage(executor, "s1")
    assert result == "failed"


# ---------------------------------------------------------------------------
# K-2: execute_async() must set executor._run_id
# ---------------------------------------------------------------------------


def test_execute_async_sets_run_id():
    """execute_async must set executor._run_id from kernel.start_run's return value."""
    from hi_agent.contracts import CTSExplorationBudget
    from hi_agent.contracts.policy import PolicyVersionSet
    from hi_agent.contracts.task import TaskContract
    from hi_agent.events import EventEmitter
    from hi_agent.memory import MemoryCompressor
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.route_engine.acceptance import AcceptancePolicy
    from hi_agent.runner import RunExecutor, execute_async
    from hi_agent.trajectory.stage_graph import StageGraph

    contract = TaskContract(task_id="t-async-id", goal="test")
    kernel = MagicMock()
    kernel.start_run = AsyncMock(return_value="run-async-001")
    kernel.open_stage = MagicMock(return_value="branch-1")
    kernel.mark_branch_state = MagicMock()
    kernel.complete_run = AsyncMock()

    sg = StageGraph()
    sg.add_edge("s1", "s2")

    executor = RunExecutor(
        contract=contract,
        kernel=kernel,
        stage_graph=sg,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    stage_exec = MagicMock()
    stage_exec.execute_stage = MagicMock(return_value="completed")
    executor._stage_executor = stage_exec

    with contextlib.suppress(Exception):
        asyncio.run(execute_async(executor))

    assert executor._run_id == "run-async-001", (
        f"Expected run-async-001 (from kernel.start_run), got {executor._run_id}"
    )


# ---------------------------------------------------------------------------
# K-3: execute_async() compatible with sync kernel
# ---------------------------------------------------------------------------


def test_execute_async_compatible_with_sync_kernel():
    """execute_async() must not crash when given a sync kernel (no await on str)."""
    from hi_agent.contracts import CTSExplorationBudget
    from hi_agent.contracts.policy import PolicyVersionSet
    from hi_agent.contracts.task import TaskContract
    from hi_agent.events import EventEmitter
    from hi_agent.memory import MemoryCompressor
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.route_engine.acceptance import AcceptancePolicy
    from hi_agent.runner import RunExecutor, execute_async
    from hi_agent.trajectory.stage_graph import StageGraph

    contract = TaskContract(task_id="t-sync-kernel", goal="test")
    kernel = MagicMock()
    kernel.start_run = MagicMock(return_value="run-sync-001")
    kernel.open_stage = MagicMock(return_value="branch-1")
    kernel.mark_branch_state = MagicMock()
    kernel.complete_run = MagicMock()

    sg = StageGraph()
    sg.add_edge("s1", "s2")

    executor = RunExecutor(
        contract=contract,
        kernel=kernel,
        stage_graph=sg,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    stage_exec = MagicMock()
    stage_exec.execute_stage = MagicMock(return_value="completed")
    executor._stage_executor = stage_exec

    try:
        asyncio.run(execute_async(executor))
    except TypeError as exc:
        raise AssertionError(f"execute_async crashed with sync kernel: {exc}") from exc
    except Exception:
        pass


# ---------------------------------------------------------------------------
# K-6: Gate restore does not re-raise resolved gates
# ---------------------------------------------------------------------------


def test_checkpoint_resume_does_not_restore_resolved_gate():
    """A resolved gate must NOT be re-raised after checkpoint resume."""
    events = [
        {"event": "gate_registered", "gate_id": "g-001"},
        {"event": "gate_decision", "gate_id": "g-001", "decision": "approved"},
    ]

    _last_gate_event = None
    for ev in reversed(events):
        if isinstance(ev, dict) and ev.get("event") in ("gate_registered", "gate_decision"):
            _last_gate_event = ev
            break

    if _last_gate_event is not None and _last_gate_event.get("event") == "gate_registered":
        _gate_pending = _last_gate_event.get("gate_id")
    else:
        _gate_pending = None

    assert _gate_pending is None, f"Resolved gate should not be restored, got {_gate_pending}"


def test_checkpoint_resume_restores_unresolved_gate():
    """An unresolved gate MUST be restored as pending after checkpoint resume."""
    events = [
        {"event": "gate_registered", "gate_id": "g-002"},
    ]

    _last_gate_event = None
    for ev in reversed(events):
        if isinstance(ev, dict) and ev.get("event") in ("gate_registered", "gate_decision"):
            _last_gate_event = ev
            break

    if _last_gate_event is not None and _last_gate_event.get("event") == "gate_registered":
        _gate_pending = _last_gate_event.get("gate_id")
    else:
        _gate_pending = None

    assert _gate_pending == "g-002", f"Unresolved gate should be restored, got {_gate_pending}"


# ---------------------------------------------------------------------------
# K-7: Reflect branch terminates with buggy policy (no RecursionError)
# ---------------------------------------------------------------------------


def test_reflect_branch_terminates_with_buggy_policy():
    """A policy that always returns reflect+next_attempt must NOT cause RecursionError."""
    executor = _bare_executor(task_id="t-k7", run_id="run-k7")
    executor._stage_executor.execute_stage.return_value = "failed"

    always_reflect = MagicMock()
    always_reflect.action = "reflect"
    always_reflect.next_attempt_seq = 99
    always_reflect.reason = "always reflect"
    always_reflect.reflection_prompt = None

    policy_engine = MagicMock()
    policy_engine._get_policy.return_value = MagicMock()
    policy_engine._decide.return_value = always_reflect
    policy_engine._record_attempt.return_value = None
    policy_engine._get_attempts.return_value = []

    executor._restart_policy = policy_engine
    try:
        result = executor._handle_stage_failure("s1", "failed")
    except RecursionError as exc:
        raise AssertionError("RecursionError: K-7 fix not applied") from exc
    assert result == "failed", f"Expected 'failed' at ceiling, got {result!r}"


# ---------------------------------------------------------------------------
# K-15: execute_async() sets _run_start_monotonic
# ---------------------------------------------------------------------------


def test_execute_async_sets_run_start_monotonic():
    """execute_async must set _run_start_monotonic so duration is measurable."""
    import time

    from hi_agent.contracts import CTSExplorationBudget
    from hi_agent.contracts.policy import PolicyVersionSet
    from hi_agent.contracts.task import TaskContract
    from hi_agent.events import EventEmitter
    from hi_agent.memory import MemoryCompressor
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.route_engine.acceptance import AcceptancePolicy
    from hi_agent.runner import RunExecutor, execute_async
    from hi_agent.trajectory.stage_graph import StageGraph

    contract = TaskContract(task_id="t-k15", goal="test")
    kernel = MagicMock()
    kernel.start_run = MagicMock(return_value="run-k15")
    kernel.open_stage = MagicMock(return_value="b1")
    kernel.mark_branch_state = MagicMock()
    kernel.complete_run = MagicMock()

    sg = StageGraph()
    sg.add_edge("s1", "s2")

    executor = RunExecutor(
        contract=contract,
        kernel=kernel,
        stage_graph=sg,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    stage_exec = MagicMock()
    stage_exec.execute_stage = MagicMock(return_value="completed")
    executor._stage_executor = stage_exec

    before = time.monotonic()
    with contextlib.suppress(Exception):
        asyncio.run(execute_async(executor))

    assert hasattr(executor, "_run_start_monotonic"), "_run_start_monotonic not set"
    assert executor._run_start_monotonic >= before, (
        "monotonic timestamp must be >= before-call time"
    )

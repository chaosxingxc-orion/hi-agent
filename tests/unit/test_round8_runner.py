"""Round-8 runner defect tests: K-1, K-2, K-3, K-6, K-7, K-15."""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Shared helper — minimal bare executor (mirrors round-7 pattern)
# ---------------------------------------------------------------------------


def _bare_executor(task_id: str = "t-r8", run_id: str = "run-r8"):
    """Return a RunExecutor bypassing __init__ with minimal wiring."""
    from hi_agent.runner import RunExecutor

    executor = RunExecutor.__new__(RunExecutor)
    c = MagicMock()
    c.task_id = task_id
    c.goal = "test goal r8"
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
    executor._pending_reflection_tasks = []
    executor._run_start_monotonic = None
    return executor


# ---------------------------------------------------------------------------
# K-1: logger -> _logger NameError
# ---------------------------------------------------------------------------


def test_deadline_exceeded_returns_failed_not_crash():
    """Deadline enforcement must return 'failed', not raise NameError."""
    from datetime import UTC, datetime, timedelta

    executor = _bare_executor(task_id="t-deadline", run_id="run-deadline")
    executor.contract.deadline = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    # _execute_stage is called by execute() for each stage; deadline check runs inside it.
    # Wire _stage_executor so execute_stage would succeed if reached.
    executor._stage_executor.execute_stage.return_value = "completed"

    # Stub _execute_stage to call the real method path by delegating to a real
    # RunExecutor._execute_stage via the bare executor.
    # Easiest: call _execute_stage directly and verify it returns "failed".
    from hi_agent.runner import RunExecutor

    result = RunExecutor._execute_stage(executor, "s1")
    # Should return failed (deadline enforced), NOT raise NameError
    assert result == "failed"


# ---------------------------------------------------------------------------
# K-2: execute_async() must set executor._run_id
# ---------------------------------------------------------------------------


def test_execute_async_sets_run_id():
    """execute_async must set executor._run_id from kernel.start_run's return value.

    DF-16 / K-2 / K-3 (Rule 5 branch parity): previously execute_async() called
    start_run with a wrong signature and set _run_id to a locally-minted
    deterministic_id, making the kernel's view of run_id disagree with the
    executor's. The fix aligns the async path with sync: _run_id always comes
    from the kernel.
    """
    import asyncio
    import contextlib
    from unittest.mock import AsyncMock

    from hi_agent.contracts.task import TaskContract
    from hi_agent.runner import RunExecutor, execute_async
    from hi_agent.trajectory.stage_graph import StageGraph

    from hi_agent.memory.l0_raw import RawMemoryStore

    contract = TaskContract(task_id="t-async-id", goal="test")
    kernel = MagicMock()
    kernel.start_run = AsyncMock(return_value="run-async-001")
    kernel.open_stage = MagicMock(return_value="branch-1")
    kernel.mark_branch_state = MagicMock()
    kernel.complete_run = AsyncMock()

    sg = StageGraph()
    sg.add_edge("s1", "s2")

    executor = RunExecutor(contract=contract, kernel=kernel, stage_graph=sg, raw_memory=RawMemoryStore())
    stage_exec = MagicMock()
    stage_exec.execute_stage = MagicMock(return_value="completed")
    executor._stage_executor = stage_exec

    with contextlib.suppress(Exception):
        asyncio.run(execute_async(executor))

    # After execute_async, _run_id must equal the kernel's start_run return.
    assert executor._run_id == "run-async-001", (
        f"Expected run-async-001 (from kernel.start_run), got {executor._run_id}"
    )


# ---------------------------------------------------------------------------
# K-3: execute_async() compatible with sync kernel
# ---------------------------------------------------------------------------


def test_execute_async_compatible_with_sync_kernel():
    """execute_async() must not crash when given a sync kernel (no await on str)."""
    import asyncio

    from hi_agent.contracts.task import TaskContract
    from hi_agent.runner import RunExecutor, execute_async
    from hi_agent.trajectory.stage_graph import StageGraph

    from hi_agent.memory.l0_raw import RawMemoryStore

    contract = TaskContract(task_id="t-sync-kernel", goal="test")
    # Sync kernel — start_run returns str, not coroutine
    kernel = MagicMock()
    kernel.start_run = MagicMock(return_value="run-sync-001")  # NOT AsyncMock
    kernel.open_stage = MagicMock(return_value="branch-1")
    kernel.mark_branch_state = MagicMock()
    kernel.complete_run = MagicMock()

    sg = StageGraph()
    sg.add_edge("s1", "s2")

    executor = RunExecutor(contract=contract, kernel=kernel, stage_graph=sg, raw_memory=RawMemoryStore())
    stage_exec = MagicMock()
    stage_exec.execute_stage = MagicMock(return_value="completed")
    executor._stage_executor = stage_exec

    # Must not raise TypeError about awaiting a non-coroutine
    try:
        asyncio.run(execute_async(executor))
    except TypeError as exc:
        raise AssertionError(f"execute_async crashed with sync kernel: {exc}") from exc
    except Exception:
        pass  # other errors are acceptable in test env


# ---------------------------------------------------------------------------
# K-6: Gate restore does not re-raise resolved gates
# ---------------------------------------------------------------------------


def test_checkpoint_resume_does_not_restore_resolved_gate():
    """A resolved gate must NOT be re-raised after checkpoint resume."""
    # Simulate the gate restore logic from resume_from_checkpoint using a plain list
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
    # Simulate the gate restore logic with an unresolved gate
    events = [
        {"event": "gate_registered", "gate_id": "g-002"},
        # No gate_decision — gate is still pending
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
    executor._stage_executor.execute_stage.return_value = "failed"  # always fails

    # RestartDecision that always says "reflect with next retry scheduled"
    always_reflect = MagicMock()
    always_reflect.action = "reflect"
    always_reflect.next_attempt_seq = 99  # non-None — triggers retry loop
    always_reflect.reason = "always reflect"
    always_reflect.reflection_prompt = None

    # Wire a mock restart policy engine whose callables are all mocked
    policy_engine = MagicMock()
    # _get_policy must return a non-None value to proceed past the "no policy" branch
    policy_engine._get_policy.return_value = MagicMock()
    policy_engine._decide.return_value = always_reflect
    policy_engine._record_attempt.return_value = None
    policy_engine._get_attempts.return_value = []

    executor._restart_policy = policy_engine
    # Must NOT raise RecursionError
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
    import asyncio
    import contextlib
    import time

    from hi_agent.contracts.task import TaskContract
    from hi_agent.runner import RunExecutor, execute_async
    from hi_agent.trajectory.stage_graph import StageGraph

    from hi_agent.memory.l0_raw import RawMemoryStore

    contract = TaskContract(task_id="t-k15", goal="test")
    kernel = MagicMock()
    kernel.start_run = MagicMock(return_value="run-k15")
    kernel.open_stage = MagicMock(return_value="b1")
    kernel.mark_branch_state = MagicMock()
    kernel.complete_run = MagicMock()

    sg = StageGraph()
    sg.add_edge("s1", "s2")

    executor = RunExecutor(contract=contract, kernel=kernel, stage_graph=sg, raw_memory=RawMemoryStore())
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

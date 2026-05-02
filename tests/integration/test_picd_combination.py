"""K-13 combination test: PI-C (Human Gate) + PI-D (subrun dispatch).

Closes K-13 from the platform-gaps.md backlog.

Pattern coverage
----------------
PI-C  — ``GatePendingError`` raised during execution; ``continue_from_gate``
         resumes the run to completion.  Gate state (``_gate_pending``) is
         cleared after approval.

PI-D  — ``dispatch_subrun`` spawns a real child run via a real
         ``DelegationManager`` backed by ``InProcessKernelStub``.
         ``await_subrun`` returns the real output from ``query_run``.
         Parent/child run IDs are distinct (Rule 13 ID uniqueness).

PI-E (K-13 target) — Both PI-C and PI-D exercised in the same ``RunExecutor``
         run (2-stage graph: subrun stage → gated stage).  Sub-run output
         propagates to the parent before the gate fires.  After
         ``continue_from_gate('approved')``, the run reaches
         ``status == 'completed'``.

No MagicMock on any subsystem under test (Rule 4 / P3 production integrity).
``InProcessKernelStub`` is a minimal real in-process implementation, not a
Mock — see ``tests/fixtures/in_process_kernel.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.gate_protocol import GatePendingError
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor, SubRunHandle, SubRunResult
from hi_agent.task_mgmt.delegation import DelegationConfig, DelegationManager
from hi_agent.trajectory.stage_graph import StageGraph

from tests.fixtures.in_process_kernel import ChildOutcome, InProcessKernelStub
from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_contract(tag: str, goal: str) -> TaskContract:
    """Return a TaskContract with a unique task_id per call."""
    return TaskContract(
        task_id=f"k13-{tag}-{uuid.uuid4().hex[:8]}",
        goal=goal,
        task_family="quick_task",
    )


def _make_executor(
    contract: TaskContract,
    *,
    delegation_manager: DelegationManager | None = None,
    stage_graph: StageGraph | None = None,
    invoker: Any | None = None,
) -> RunExecutor:
    """Wire up a RunExecutor with a real MockKernel (no LLM required)."""
    kernel = MockKernel(strict_mode=False)
    return RunExecutor(
        contract,
        kernel,
        stage_graph=stage_graph,
        invoker=invoker,
        delegation_manager=delegation_manager,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )


# ---------------------------------------------------------------------------
# PI-C: gate round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_pi_c_gate_approve_resumes_run() -> None:
    """PI-C: execute() raises GatePendingError; continue_from_gate('approved') completes the run.

    Verifies:
    - register_gate sets ``_gate_pending`` to the gate_id.
    - execute() propagates GatePendingError (does not swallow it).
    - continue_from_gate with 'approved' decision drives the run to 'completed'.
    - ``_gate_pending`` is cleared after the decision.
    """
    graph = StageGraph()
    graph.add_edge("pi_c_stage_a", "pi_c_stage_b")

    class _AlwaysSucceedInvoker:
        """Returns success for every stage — no LLM required."""

        def invoke(self, capability_name: str, payload: dict) -> dict:
            stage_id = payload.get("stage_id", capability_name)
            return {"success": True, "score": 1.0, "evidence_hash": f"ev_{stage_id}"}

    contract = _make_contract("pic-approve", "PI-C gate approve round-trip")
    executor = _make_executor(
        contract, stage_graph=graph, invoker=_AlwaysSucceedInvoker()
    )

    gate_id = f"gate-pic-{uuid.uuid4().hex[:6]}"
    gate_fired = [False]
    original_execute_stage = executor._execute_stage

    def gated_stage(stage_id: str) -> str | None:
        if stage_id == "pi_c_stage_a" and not gate_fired[0]:
            gate_fired[0] = True
            executor.register_gate(gate_id, "final_approval", phase_name="pi_c_stage_a")
            raise GatePendingError(gate_id=gate_id)
        return original_execute_stage(stage_id)

    executor._execute_stage = gated_stage  # type: ignore[method-assign]  expiry_wave: Wave 30

    with pytest.raises(GatePendingError) as exc_info:
        executor.execute()

    assert exc_info.value.gate_id == gate_id
    assert executor._gate_pending == gate_id

    result = executor.continue_from_gate(gate_id, "approved")

    assert str(result) == "completed", (
        f"PI-C: expected 'completed' after approval, got {result!r}"
    )
    assert executor._gate_pending is None, "gate must be cleared after continue_from_gate"


@pytest.mark.integration
def test_pi_c_gate_backtrack_terminates_run() -> None:
    """PI-C: continue_from_gate('backtrack') drives the run to 'failed' (intentional termination).

    Verifies:
    - The 'backtrack' decision causes a definitive terminal status of 'failed'.
    - ``_gate_pending`` is cleared regardless of decision.
    """
    graph = StageGraph()
    graph.add_edge("pi_c_s1", "pi_c_s2")

    class _AlwaysSucceedInvoker2:
        """Returns success for every stage — no LLM required."""

        def invoke(self, capability_name: str, payload: dict) -> dict:
            stage_id = payload.get("stage_id", capability_name)
            return {"success": True, "score": 1.0, "evidence_hash": f"ev_{stage_id}"}

    contract = _make_contract("pic-backtrack", "PI-C gate backtrack round-trip")
    executor = _make_executor(
        contract, stage_graph=graph, invoker=_AlwaysSucceedInvoker2()
    )

    gate_id = f"gate-pic-bt-{uuid.uuid4().hex[:6]}"
    gate_fired = [False]
    original_execute_stage = executor._execute_stage

    def gated_stage(stage_id: str) -> str | None:
        if stage_id == "pi_c_s1" and not gate_fired[0]:
            gate_fired[0] = True
            executor.register_gate(gate_id, "route_direction", phase_name="pi_c_s1")
            raise GatePendingError(gate_id=gate_id)
        return original_execute_stage(stage_id)

    executor._execute_stage = gated_stage  # type: ignore[method-assign]  expiry_wave: Wave 30

    with pytest.raises(GatePendingError):
        executor.execute()

    result = executor.continue_from_gate(gate_id, "backtrack")

    assert str(result) == "failed", (
        f"PI-C: backtrack decision must yield 'failed', got {result!r}"
    )
    assert executor._gate_pending is None


# ---------------------------------------------------------------------------
# PI-D: subrun dispatch and await
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_pi_d_dispatch_and_await_subrun() -> None:
    """PI-D: dispatch_subrun dispatches a real child run; await_subrun returns its output.

    Verifies:
    - dispatch_subrun returns a SubRunHandle (not a Mock).
    - await_subrun returns SubRunResult with success=True and non-empty output.
    - InProcessKernelStub recorded one spawn call; parent/child IDs are distinct
      (Rule 13 ID uniqueness).
    - No fallback events are emitted on the happy path.
    """
    from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events

    child_kernel = InProcessKernelStub(
        default_outcome=ChildOutcome(
            lifecycle_state="completed",
            output="k13-PI-D real subrun output",
        ),
    )
    delegation_mgr = DelegationManager(
        kernel=child_kernel,
        config=DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01),
    )

    contract = _make_contract("pid-dispatch", "PI-D subrun dispatch and await")
    executor = _make_executor(contract, delegation_manager=delegation_mgr)

    parent_run_id = f"run-k13-pid-{uuid.uuid4().hex[:8]}"
    executor._run_id = parent_run_id
    clear_fallback_events(parent_run_id)

    handle = executor.dispatch_subrun(
        agent="research",
        profile_id="k13-test-profile",
        goal="K-13 PI-D child task goal",
    )

    assert isinstance(handle, SubRunHandle), (
        f"dispatch_subrun must return SubRunHandle, got {type(handle)!r}"
    )
    assert handle.agent == "research"

    result = executor.await_subrun(handle)

    assert isinstance(result, SubRunResult), (
        f"await_subrun must return SubRunResult, got {type(result)!r}"
    )
    assert result.success is True, f"PI-D sub-run must succeed; got {result!r}"
    assert result.error is None
    assert "k13-PI-D real subrun output" in result.output, (
        f"output must come from InProcessKernelStub query_run; got {result.output!r}"
    )

    assert len(child_kernel.spawn_calls) >= 1, (
        f"at least one child spawn expected; got {child_kernel.spawn_calls!r}"
    )
    spawn = child_kernel.spawn_calls[0]
    assert spawn["parent_run_id"] == parent_run_id
    assert spawn["child_run_id"] != parent_run_id, (
        "child_run_id must be distinct from parent_run_id (Rule 13)"
    )
    assert spawn["child_run_id"].startswith("child-")

    # No fallback events on the PI-D happy path.
    assert get_fallback_events(parent_run_id) == [], (
        "PI-D happy path must not emit fallback events"
    )


@pytest.mark.integration
def test_pi_d_dispatch_subrun_requires_delegation_manager() -> None:
    """PI-D: dispatch_subrun raises RuntimeError when no DelegationManager is wired.

    Verifies the fail-fast error — callers cannot silently dispatch with no manager.
    """
    contract = _make_contract("pid-no-mgr", "PI-D guard: no delegation manager")
    executor = _make_executor(contract, delegation_manager=None)

    assert executor._delegation_manager is None

    with pytest.raises(RuntimeError, match="DelegationManager"):
        executor.dispatch_subrun(agent="analyzer", profile_id="default")


# ---------------------------------------------------------------------------
# PI-E (K-13): PI-C + PI-D in a single run (the combination target)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_pi_e_gate_and_subrun_in_single_run() -> None:
    """PI-E (K-13): dispatch_subrun (PI-D) + human gate + resume (PI-C) in one run.

    Scenario (2 stages):
      1. ``k13_s_sub``   — PI-D: dispatch a child run; await and store output.
      2. ``k13_s_final`` — PI-C: register a gate and raise GatePendingError on
                           the first visit.  Second visit (after
                           continue_from_gate('approved')) runs to completion.

    Invariants:
      * PI-D: sub-run output propagated before gate fires; spawn IDs distinct.
      * PI-C: GatePendingError carries expected gate_id; _gate_pending cleared
              after approval.
      * PI-E: final result.status == 'completed' with no fallback events.

    No MagicMock anywhere — InProcessKernelStub is a real in-process
    implementation, not a Mock (P3 production integrity).
    """
    from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events

    # --- PI-D setup: real DelegationManager over InProcessKernelStub --------
    child_kernel = InProcessKernelStub(
        default_outcome=ChildOutcome(
            lifecycle_state="completed",
            output="k13-pi-e subrun result",
        ),
    )
    delegation_mgr = DelegationManager(
        kernel=child_kernel,
        config=DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01),
    )

    # --- 2-stage graph: subrun stage → gated stage --------------------------
    graph = StageGraph()
    graph.add_edge("k13_s_sub", "k13_s_final")

    artifact_store: dict[str, Any] = {}

    # The invoker needs a reference to the executor it runs inside.
    # We defer wiring via a mutable cell so the invoker closure can call
    # executor.dispatch_subrun / executor.await_subrun once constructed.
    executor_cell: list[RunExecutor] = []

    class K13Invoker:
        """Invokes PI-D dispatch on k13_s_sub; succeeds cleanly on k13_s_final."""

        def invoke(
            self,
            capability_name: str,
            payload: dict,
            role: str | None = None,
            metadata: dict | None = None,
        ) -> dict:
            stage_id = payload.get("stage_id", capability_name)
            if stage_id == "k13_s_sub":
                _exec = executor_cell[0]
                handle = _exec.dispatch_subrun(
                    agent="research",
                    profile_id="k13-child-profile",
                    goal="K-13 PI-E child task",
                )
                sr = _exec.await_subrun(handle)
                artifact_store["subrun_success"] = sr.success
                artifact_store["subrun_output"] = sr.output
            return {"success": True, "score": 1.0, "evidence_hash": f"ev_{stage_id}"}

    invoker = K13Invoker()

    contract = _make_contract("pie-combo", "PI-E K-13: gate + subrun combination")
    executor = _make_executor(
        contract,
        delegation_manager=delegation_mgr,
        stage_graph=graph,
        invoker=invoker,
    )
    executor_cell.append(executor)

    # Pre-clear fallback store before execute() assigns the real run_id.
    pre_run_id = f"run-k13-{uuid.uuid4().hex[:8]}"
    executor._run_id = pre_run_id
    clear_fallback_events(pre_run_id)

    # --- PI-C: wrap _execute_stage to fire gate on k13_s_final first visit --
    gate_id = f"gate-k13-{uuid.uuid4().hex[:6]}"
    gate_fired = [False]
    original_execute_stage = executor._execute_stage

    def gated_execute_stage(stage_id: str) -> str | None:
        if stage_id == "k13_s_final" and not gate_fired[0]:
            gate_fired[0] = True
            executor.register_gate(gate_id, "final_approval", phase_name="k13_s_final")
            raise GatePendingError(gate_id=gate_id)
        return original_execute_stage(stage_id)

    executor._execute_stage = gated_execute_stage  # type: ignore[method-assign]  expiry_wave: Wave 30

    # --- Phase 1: execute() runs k13_s_sub (PI-D), then hits gate (PI-C) ----
    with pytest.raises(GatePendingError) as exc_info:
        executor.execute()

    assert exc_info.value.gate_id == gate_id, (
        f"GatePendingError must carry expected gate_id; got {exc_info.value.gate_id!r}"
    )
    assert executor._gate_pending == gate_id

    # PI-D invariants — sub-run completed before the gate fired.
    assert artifact_store.get("subrun_success") is True, (
        f"PI-D sub-run must complete before gate; got {artifact_store!r}"
    )
    assert "k13-pi-e subrun result" in str(artifact_store.get("subrun_output", "")), (
        f"sub-run output must propagate to parent; got {artifact_store!r}"
    )

    assert len(child_kernel.spawn_calls) >= 1, (
        f"DelegationManager must have spawned at least one child; "
        f"got {child_kernel.spawn_calls!r}"
    )
    spawn = child_kernel.spawn_calls[0]
    assert spawn["parent_run_id"] == executor.run_id
    assert spawn["parent_run_id"].strip() != ""
    assert spawn["child_run_id"] != spawn["parent_run_id"], (
        "child_run_id must differ from parent_run_id (Rule 13 ID uniqueness)"
    )
    assert spawn["child_run_id"].startswith("child-")

    # --- Phase 2: approve gate → run completes ----------------------------
    result = executor.continue_from_gate(gate_id, "approved")

    assert str(result) == "completed", (
        f"PI-E: expected 'completed' after gate approval, got {result!r}"
    )
    assert executor._gate_pending is None, "gate must be cleared after continue_from_gate"

    # PI-E composition: no heuristic fallback on the happy path.
    assert get_fallback_events(executor.run_id) == [], (
        f"PI-E happy path must not emit fallback events; "
        f"got {get_fallback_events(executor.run_id)!r}"
    )

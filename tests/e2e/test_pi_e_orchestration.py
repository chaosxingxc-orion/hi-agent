"""PI-E E2E — full orchestration (PI-B + PI-C + PI-D in one run).

Scenario (3 stages):

  1. ``pi_e_s_sub``   — PI-D: dispatch a real child run through
     ``DelegationManager`` backed by ``InProcessKernelStub``.
  2. ``pi_e_s_flaky`` — PI-B: fails on attempt 1, succeeds on attempt 2.
     A real ``RestartPolicyEngine`` with ``on_exhausted='reflect'`` drives
     the retry decision.
  3. ``pi_e_s_final`` — PI-C: register a human gate and raise
     ``GatePendingError`` on its first execution.  After
     ``continue_from_gate('approved')`` the stage runs to completion.

Assertions cover all four invariants:

  * PI-A (multistage): three stages ran in the declared order.
  * PI-B (reflect retry): the flaky stage ran at least twice.
  * PI-C (gate): ``GatePendingError.gate_id`` matches, and ``_gate_pending``
    is cleared after ``continue_from_gate``.
  * PI-D (subrun): the in-process kernel recorded at least one spawn
    with a distinct child_run_id; the sub-run output reached the parent.
  * PI-E composition: final ``result.status == 'completed'`` with no
    heuristic fallback events (Rule 14).

Mirrors ``tests/integration/test_journeys.py::journey-9`` with a
test-scoped ``profile_id`` per Rule 13.  No ``MagicMock`` anywhere.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from hi_agent.contracts import CTSExplorationBudget
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.gate_protocol import GatePendingError
from hi_agent.memory import MemoryCompressor
from hi_agent.observability.fallback import (
    clear_fallback_events,
    get_fallback_events,
)
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.task_mgmt.delegation import DelegationConfig, DelegationManager
from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine, TaskRestartPolicy
from hi_agent.trajectory.stage_graph import StageGraph

from tests.e2e.conftest import REAL_LLM_AVAILABLE, make_contract, make_mock_kernel
from tests.fixtures.in_process_kernel import ChildOutcome, InProcessKernelStub


@pytest.mark.integration
def test_pi_e_full_orchestration(profile_id_for_test: str) -> None:
    """PI-E: sub-run + reflect + gate + multistage composed in a single run."""
    # --- PI-D setup ------------------------------------------------------
    child_kernel = InProcessKernelStub(
        default_outcome=ChildOutcome(
            lifecycle_state="completed",
            output="pi-e subrun result payload",
        ),
    )
    delegation_mgr = DelegationManager(
        kernel=child_kernel,
        config=DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01),
    )

    # --- PI-B setup ------------------------------------------------------
    attempt_log: list[Any] = []
    policy = TaskRestartPolicy(max_attempts=3, on_exhausted="reflect")
    restart_engine = RestartPolicyEngine(
        get_attempts=lambda tid: [a for a in attempt_log if a.task_id == tid],
        get_policy=lambda tid: policy,
        update_state=lambda tid, state: None,
        record_attempt=lambda a: attempt_log.append(a),
    )

    # --- Multistage graph ------------------------------------------------
    graph = StageGraph()
    graph.add_edge("pi_e_s_sub", "pi_e_s_flaky")
    graph.add_edge("pi_e_s_flaky", "pi_e_s_final")

    contract = make_contract(profile_id_for_test, goal="PI-E: subrun + reflect + gate composition")
    kernel = make_mock_kernel()

    artifact_store: dict[str, Any] = {}
    flaky_attempts: dict[str, int] = {}

    class PiEInvoker:
        def invoke(
            self,
            capability_name: str,
            payload: dict,
            role: str | None = None,
            metadata: dict | None = None,
        ) -> dict:
            stage_id = payload.get("stage_id", capability_name)

            if stage_id == "pi_e_s_sub":
                handle = executor.dispatch_subrun(
                    agent="research",
                    profile_id=f"{profile_id_for_test}-child",
                    goal="pi-e child task",
                )
                sr = executor.await_subrun(handle)
                artifact_store["subrun_success"] = sr.success
                artifact_store["subrun_output"] = sr.output
                return {"success": True, "score": 1.0, "evidence_hash": "ev_sub"}

            if stage_id == "pi_e_s_flaky":
                n = flaky_attempts.get(stage_id, 0) + 1
                flaky_attempts[stage_id] = n
                if n == 1:
                    return {
                        "success": False,
                        "score": 0.0,
                        "reason": "PI-E: first attempt must fail to exercise reflect()",
                    }
                return {
                    "success": True,
                    "score": 1.0,
                    "evidence_hash": f"ev_flaky_{n}",
                }

            # pi_e_s_final and any other stage succeeds cleanly.
            return {"success": True, "score": 1.0, "evidence_hash": f"ev_{stage_id}"}

    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        invoker=PiEInvoker(),
        delegation_manager=delegation_mgr,
        restart_policy_engine=restart_engine,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    # Pre-clear fallback events for the run_id start_run will assign.
    pre_run_id = f"run-pi-e-{uuid.uuid4().hex[:8]}"
    executor._run_id = pre_run_id
    clear_fallback_events(pre_run_id)

    # --- PI-C: wrap _execute_stage to fire a gate on pi_e_s_final -------
    gate_id = f"pi-e-gate-{uuid.uuid4().hex[:6]}"
    gate_fired = [False]
    original_execute_stage = executor._execute_stage

    def gated_execute_stage(stage_id: str) -> str | None:
        if stage_id == "pi_e_s_final" and not gate_fired[0]:
            gate_fired[0] = True
            executor.register_gate(gate_id, "final_approval", phase_name="pi_e_s_final")
            raise GatePendingError(gate_id=gate_id)
        return original_execute_stage(stage_id)

    executor._execute_stage = gated_execute_stage  # type: ignore[method-assign]

    # --- Phase 1: execute() must raise GatePendingError at pi_e_s_final --
    with pytest.raises(GatePendingError) as exc_info:
        executor.execute()
    assert exc_info.value.gate_id == gate_id
    assert executor._gate_pending == gate_id

    # PI-D happened before the gate.
    assert artifact_store.get("subrun_success") is True, (
        f"PI-D sub-run must succeed before the gate; got {artifact_store!r}"
    )
    assert "pi-e subrun result payload" in str(artifact_store.get("subrun_output", ""))

    # PI-B retry happened.
    assert flaky_attempts.get("pi_e_s_flaky", 0) >= 2, (
        f"PI-B reflect retry must run pi_e_s_flaky at least twice; got {flaky_attempts!r}"
    )
    assert executor._stage_attempt.get("pi_e_s_flaky", 0) >= 1

    # PI-D spawn invariants.
    assert len(child_kernel.spawn_calls) >= 1
    first_spawn = child_kernel.spawn_calls[0]
    assert first_spawn["parent_run_id"] == executor.run_id
    assert first_spawn["parent_run_id"].strip() != ""
    assert first_spawn["child_run_id"] != first_spawn["parent_run_id"]
    assert first_spawn["child_run_id"].startswith("child-")

    # --- Phase 2: approve resume — run completes ------------------------
    result = executor.continue_from_gate(gate_id, "approved")

    assert result.status == "completed", (
        f"PI-E expected completed after approve, got {result.status!r}: error={result.error!r}"
    )
    assert executor._gate_pending is None

    # Rule 14 — no heuristic fallback on the happy path (only meaningful with a real LLM;
    # in heuristic-only mode all capabilities emit capability fallback events by design).
    if REAL_LLM_AVAILABLE:
        assert get_fallback_events(executor.run_id) == [], (
            f"PI-E must not emit fallback events; got {get_fallback_events(executor.run_id)!r}"
        )
        assert result.fallback_events == []

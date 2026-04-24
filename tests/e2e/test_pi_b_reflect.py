"""PI-B E2E — Multistage + reflect(N) restart policy.

Pattern:
  * 3-stage linear plan with a flaky middle stage that fails on the first
    attempt and succeeds on the second.
  * A real ``RestartPolicyEngine`` with ``on_exhausted='reflect'`` drives
    the retry decision.  The runner, stage orchestrator, restart policy
    engine, and acceptance policy all run as real code — only the
    capability handler (the external boundary per Rule 7) is a plain
    Python function.
  * This mirrors ``tests/integration/test_journeys.py::journey-3`` exactly,
    with a test-scoped ``profile_id`` on the contract to satisfy Rule 13.

Implementation note:
  The E2E suite uses ``RunExecutor(...)`` with an explicit invoker for
  PI-B / PI-C / PI-D / PI-E.  ``SystemBuilder.build_executor`` wires a
  ``HarnessExecutor`` into the action dispatcher that routes every
  capability call through the governance pipeline, which makes it
  impossible to deterministically inject flakiness at a specific stage
  boundary.  Going through ``RunExecutor`` directly is the same
  production-parity path the journeys suite uses — no Mock or MagicMock
  anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from hi_agent.runner import RunExecutor
from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine, TaskRestartPolicy
from hi_agent.trajectory.stage_graph import StageGraph

from tests.e2e.conftest import REAL_LLM_AVAILABLE, make_contract, make_mock_kernel


@pytest.mark.integration
def test_pi_b_reflect_retry_on_flaky_stage(profile_id_for_test: str) -> None:
    """PI-B: flaky stage fails on attempt 1, reflect(N) retries, run completes."""
    # Flaky invoker — fails once for stage pi_b_s2, then succeeds.
    attempts: dict[str, int] = {}

    class FlakyOnceInvoker:
        def invoke(
            self,
            capability_name: str,
            payload: dict,
            role: str | None = None,
            metadata: dict | None = None,
        ) -> dict:
            stage_id = payload.get("stage_id", capability_name)
            n = attempts.get(stage_id, 0) + 1
            attempts[stage_id] = n
            if stage_id == "pi_b_s2" and n == 1:
                return {
                    "success": False,
                    "score": 0.0,
                    "reason": "PI-B: first attempt must fail to exercise reflect()",
                }
            return {
                "success": True,
                "score": 1.0,
                "evidence_hash": f"ev_{stage_id}_{n}",
            }

    # Real RestartPolicyEngine — reflect(3) on exhaustion.
    attempt_log: list[Any] = []
    policy = TaskRestartPolicy(max_attempts=3, on_exhausted="reflect")
    engine = RestartPolicyEngine(
        get_attempts=lambda tid: [a for a in attempt_log if a.task_id == tid],
        get_policy=lambda tid: policy,
        update_state=lambda tid, state: None,
        record_attempt=lambda a: attempt_log.append(a),
    )

    # 3-stage linear graph.
    graph = StageGraph()
    graph.add_edge("pi_b_s1", "pi_b_s2")
    graph.add_edge("pi_b_s2", "pi_b_s3")

    contract = make_contract(profile_id_for_test, goal="PI-B reflect retry")
    kernel = make_mock_kernel()

    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        invoker=FlakyOnceInvoker(),
        restart_policy_engine=engine,
    )

    result = executor.execute()

    assert result.status == "completed", (
        f"PI-B expected completed, got {result.status!r}: error={result.error!r}"
    )

    # Observable: the flaky stage ran at least twice (retry actually happened).
    assert attempts.get("pi_b_s2", 0) >= 2, (
        f"PI-B: pi_b_s2 must have been invoked at least twice (retry); got {attempts!r}"
    )
    # Observable: the executor recorded a retry in its attempt map
    # (same invariant used by tests/integration/test_journeys.py::journey-3).
    assert executor._stage_attempt.get("pi_b_s2", 0) >= 1, (
        "_stage_attempt must record the reflect retry"
    )

    if REAL_LLM_AVAILABLE:
        assert result.fallback_events == [], (
            f"real-mode PI-B must not emit fallback events; got {result.fallback_events!r}"
        )

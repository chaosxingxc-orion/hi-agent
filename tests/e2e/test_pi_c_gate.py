"""PI-C E2E — Multistage + Human Gate.

Pattern:
  * 3-stage linear plan; a gate fires before the middle stage executes.
  * ``execute()`` raises :class:`GatePendingError` — the test inspects
    the structured ``gate_id`` attribute (Round-3 D-1 pattern).
  * ``continue_from_gate(..., 'approved')`` resumes the run; the gated
    stage and all downstream stages then execute, and the run reaches
    ``completed``.
  * Real executor, real stage graph, real ``MockKernel`` (backed by the
    agent-kernel LocalFSM).  No Mock / MagicMock anywhere.
"""

from __future__ import annotations

import pytest
from hi_agent.contracts import CTSExplorationBudget
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.gate_protocol import GatePendingError
from hi_agent.memory import MemoryCompressor
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.trajectory.stage_graph import StageGraph

from tests.e2e.conftest import REAL_LLM_AVAILABLE, make_contract, make_mock_kernel


@pytest.mark.integration
def test_pi_c_gate_blocks_then_resumes(profile_id_for_test: str) -> None:
    """PI-C: a human gate blocks the middle stage; approve resumes to completed."""
    executed_stages: list[str] = []

    class RecordingInvoker:
        def invoke(
            self,
            capability_name: str,
            payload: dict,
            role: str | None = None,
            metadata: dict | None = None,
        ) -> dict:
            executed_stages.append(payload.get("stage_id", capability_name))
            return {"success": True, "score": 1.0, "evidence_hash": "ev_ok"}

    graph = StageGraph()
    graph.add_edge("pi_c_s1", "pi_c_s2")
    graph.add_edge("pi_c_s2", "pi_c_s3")

    contract = make_contract(profile_id_for_test, goal="PI-C human gate")
    kernel = make_mock_kernel()
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        invoker=RecordingInvoker(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    gate_id = f"pi-c-gate-{profile_id_for_test}"
    gate_fired = [False]
    original_execute_stage = executor._execute_stage

    def gated_execute_stage(stage_id: str) -> str | None:
        if stage_id == "pi_c_s2" and not gate_fired[0]:
            gate_fired[0] = True
            executor.register_gate(gate_id, "artifact_review", phase_name="pi_c_s2")
            raise GatePendingError(gate_id=gate_id)
        return original_execute_stage(stage_id)

    executor._execute_stage = gated_execute_stage  # type: ignore[method-assign]

    # Phase 1 — execute() must raise GatePendingError with a structured gate_id.
    with pytest.raises(GatePendingError) as exc_info:
        executor.execute()
    assert exc_info.value.gate_id == gate_id, (
        f"GatePendingError must carry gate_id={gate_id!r}; got {exc_info.value.gate_id!r}"
    )
    assert executor._gate_pending == gate_id
    # Only the pre-gate stage has executed so far.
    assert "pi_c_s1" in executed_stages
    assert "pi_c_s3" not in executed_stages, (
        f"post-gate stage must not have run yet; executed={executed_stages!r}"
    )

    # Phase 2 — approve resume.
    result = executor.continue_from_gate(gate_id, "approved")
    assert result.status == "completed", (
        f"PI-C expected completed after approve, got {result.status!r}: error={result.error!r}"
    )
    assert executor._gate_pending is None, "gate must be cleared after resume"

    # Both the gated stage and its successor executed after resume.
    assert "pi_c_s2" in executed_stages
    assert "pi_c_s3" in executed_stages
    assert executed_stages.index("pi_c_s2") < executed_stages.index("pi_c_s3"), (
        f"post-gate stages ran out of order: {executed_stages!r}"
    )

    if REAL_LLM_AVAILABLE:
        assert result.fallback_events == [], (
            f"real-mode PI-C must not emit fallback events; got {result.fallback_events!r}"
        )

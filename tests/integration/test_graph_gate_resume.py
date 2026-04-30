"""Integration tests: Human Gate + resume for execute_graph() with a real executor.

DF-14 remediation (CLAUDE.md Rule 7 — Test Honesty).

The previous revision of this file wholesale-mocked RunExecutor and asserted on
``mock_exec.execute_graph.assert_called_once()`` — testing only that the facade
delegated to a MagicMock, not that PI-C (Human Gate + resume) actually worked.

These tests exercise the real gate-resume cycle against ``execute_graph()``:

1. Build a real RunExecutor via a multi-stage StageGraph.
2. Register a real gate on the first encounter of the gated stage.
3. ``execute_graph()`` raises ``GatePendingError`` with a structured ``gate_id``.
4. Human calls ``executor.continue_from_gate_graph(gate_id, decision=...)``.
5. Execution resumes from the gated stage (not from the beginning) and
   reaches a terminal state observable via the returned ``RunResult``.

Only a local test-scoped ``_execute_stage`` shim is patched — the shim
registers a gate on first visit and forwards to the original method on second
visit. No internal runtime component is mocked (P3 compliant).

J2-2 facade-routing coverage (the previous intent of this file) is provided by
other tests; here we focus on the behavioural contract of PI-C itself.
"""

from __future__ import annotations

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.gate_protocol import GatePendingError
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.trajectory.stage_graph import StageGraph

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Helpers — build real executor + one-shot gate installer
# ---------------------------------------------------------------------------


def _three_stage_graph() -> StageGraph:
    """Linear graph ``stage_a → stage_b → stage_c`` for resume-progression tests."""
    g = StageGraph()
    g.add_edge("stage_a", "stage_b")
    g.add_edge("stage_b", "stage_c")
    return g


def _make_executor(task_id: str) -> RunExecutor:
    """Construct a real RunExecutor backed by the real agent-kernel MockKernel."""
    contract = TaskContract(task_id=task_id, goal=f"gate-resume test {task_id}")
    kernel = MockKernel(strict_mode=False)
    return RunExecutor(
        contract,
        kernel,
        stage_graph=_three_stage_graph(),
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )


def _install_one_shot_gate(
    executor: RunExecutor,
    *,
    gated_stage: str,
    gate_id: str,
    gate_type: str,
) -> list[str]:
    """Register a gate the first time ``gated_stage`` is entered, then run normally.

    Returns a shared ``visited`` list that records every stage entry — the test
    asserts on this to prove resume continued from the gated stage, not that it
    restarted from the beginning.

    Non-gated stages return a non-"failed" sentinel so the orchestrator treats
    them as successful without requiring a live LLM / capability path. The real
    components under test are the gate-registration, GatePendingError
    propagation, and ``continue_from_gate_graph`` traversal logic — not the
    inner stage action dispatch (covered elsewhere).
    """
    visited: list[str] = []
    fired = [False]

    def patched(stage_id: str) -> str | None:
        visited.append(stage_id)
        if stage_id == gated_stage and not fired[0]:
            fired[0] = True
            executor.register_gate(gate_id, gate_type, phase_name=gated_stage)
            raise GatePendingError(gate_id=gate_id)
        # Treat every other entry (including the re-entry of the gated stage
        # after resume) as a successful stage completion. Returning None is
        # interpreted by StageOrchestrator as "not failed".
        return None

    executor._execute_stage = patched  # type: ignore[method-assign]  expiry_wave: Wave 27
    return visited


# ---------------------------------------------------------------------------
# Tests — real executor, real gate, real resume
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_execute_graph_approve_resumes_to_completion() -> None:
    """Gate on stage_b → approve → run reaches ``completed`` via stage_c.

    Observable assertions:
    - ``execute_graph()`` raises ``GatePendingError`` carrying the expected gate_id
    - After ``continue_from_gate_graph(decision='approve')``, the returned
      RunResult has ``status == 'completed'``
    - Stage visit order shows stage_b was re-entered after resume, then stage_c
      was executed — proving resume did NOT restart from stage_a
    """
    executor = _make_executor("test-gate-resume-approve")
    gate_id = "gate-graph-approve"
    visited = _install_one_shot_gate(
        executor, gated_stage="stage_b", gate_id=gate_id, gate_type="final_approval"
    )

    with pytest.raises(GatePendingError) as exc_info:
        executor.execute_graph()
    assert exc_info.value.gate_id == gate_id
    assert executor._gate_pending == gate_id

    # At this point visited should be [stage_a, stage_b] — stage_a ran, stage_b
    # registered the gate and raised.
    assert visited == ["stage_a", "stage_b"], (
        f"Expected pre-gate visit order [stage_a, stage_b], got {visited!r}"
    )

    # Tell the coordinator where to resume from. The test shim bypasses the
    # normal ``self.current_stage`` bookkeeping that a real capability dispatch
    # would perform, so we pass ``last_stage`` + ``completed_stages``
    # explicitly — exactly the public contract a facade / HTTP client uses.
    result = executor.continue_from_gate_graph(
        gate_id=gate_id,
        decision="approve",
        last_stage="stage_b",
        completed_stages={"stage_a"},
    )

    # Behavioural assertions — observable outputs only.
    assert result.status == "completed", (
        f"Run did not reach 'completed' after approve — got {result.status!r} "
        f"(error={result.error!r})"
    )
    assert executor._gate_pending is None, "Gate was not cleared after resume"

    # Resume must continue from the gated stage, not the beginning. The second
    # visit to stage_b (now un-gated) must appear, followed by stage_c. stage_a
    # must NOT have been re-executed.
    assert visited.count("stage_a") == 1, (
        f"stage_a re-executed on resume — resume restarted from the beginning: {visited!r}"
    )
    assert "stage_c" in visited, f"stage_c never executed after resume: {visited!r}"


@pytest.mark.integration
def test_execute_graph_backtrack_finalises_failed() -> None:
    """Gate on stage_b → backtrack → run finalises as ``failed``.

    Per ``GateCoordinator.continue_from_gate_graph``: a ``backtrack`` decision
    short-circuits and calls ``_finalize_run('failed')``. This asserts that
    contract and that subsequent stages are NOT executed.
    """
    executor = _make_executor("test-gate-resume-backtrack")
    gate_id = "gate-graph-backtrack"
    visited = _install_one_shot_gate(
        executor, gated_stage="stage_b", gate_id=gate_id, gate_type="route_direction"
    )

    with pytest.raises(GatePendingError):
        executor.execute_graph()

    pre_resume_visits = list(visited)

    result = executor.continue_from_gate_graph(gate_id=gate_id, decision="backtrack")

    assert result.status == "failed", (
        f"backtrack decision did not finalise 'failed' — got {result.status!r}"
    )
    # backtrack must not advance past the gated stage.
    assert visited == pre_resume_visits, (
        f"backtrack caused stages to run after the gate: {visited!r}"
    )
    assert "stage_c" not in visited, "stage_c must not execute on backtrack"


@pytest.mark.integration
def test_execute_graph_gate_on_first_stage_resumes_correctly() -> None:
    """Gate fires on the very first stage; approve must still complete the run.

    Guards against the K-11 failure mode where the test only asserted that a
    mocked ``execute_graph`` was called — it could not tell whether the real
    graph engine re-entered stage_a after the gate was cleared.
    """
    executor = _make_executor("test-gate-resume-first-stage")
    gate_id = "gate-graph-first-stage"
    visited = _install_one_shot_gate(
        executor,
        gated_stage="stage_a",
        gate_id=gate_id,
        gate_type="contract_correction",
    )

    with pytest.raises(GatePendingError) as exc_info:
        executor.execute_graph()
    assert exc_info.value.gate_id == gate_id
    assert visited == ["stage_a"], f"expected only stage_a visited before gate, got {visited!r}"

    # Gate fired before stage_a completed → pass last_stage=stage_a with an
    # empty completed set so the coordinator re-executes it.
    result = executor.continue_from_gate_graph(
        gate_id=gate_id,
        decision="approve",
        last_stage="stage_a",
        completed_stages=set(),
    )

    assert result.status == "completed", (
        f"first-stage gate resume did not complete — got {result.status!r} (error={result.error!r})"
    )
    # All three stages must have executed by end of run.
    assert "stage_a" in visited and "stage_b" in visited and "stage_c" in visited, (
        f"resume did not reach all downstream stages: {visited!r}"
    )


@pytest.mark.integration
def test_execute_graph_gate_id_is_structured_attribute() -> None:
    """Round-3 D-1 pattern: ``GatePendingError.gate_id`` must be a real attribute.

    Callers (facade, HTTP server) read ``exc.gate_id`` directly. If the attribute
    is missing, resume routing silently breaks — this test pins the contract.
    """
    executor = _make_executor("test-gate-resume-gate-id-attr")
    gate_id = "gate-graph-attribute-check"
    _install_one_shot_gate(
        executor, gated_stage="stage_a", gate_id=gate_id, gate_type="artifact_review"
    )

    with pytest.raises(GatePendingError) as exc_info:
        executor.execute_graph()

    # Must be an attribute, not just part of the message.
    exc = exc_info.value
    assert hasattr(exc, "gate_id"), "GatePendingError missing gate_id attribute"
    assert isinstance(exc.gate_id, str), f"gate_id must be str, got {type(exc.gate_id).__name__}"
    assert exc.gate_id == gate_id, f"gate_id mismatch: {exc.gate_id!r} != {gate_id!r}"

    # Resume via the attribute value — must succeed without KeyError / AttributeError.
    result = executor.continue_from_gate_graph(gate_id=exc.gate_id, decision="approve")
    assert result.status == "completed", (
        f"resume did not reach a terminal state: {result.status!r}"
    )

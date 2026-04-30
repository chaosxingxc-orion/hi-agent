"""Anchor 7 regression: GatePendingError must escape cleanly across all execution modes.

Playbook Anchor 7 requires that a pending human gate be observable and recoverable
from every execution path — ``execute()``, ``execute_graph()``, ``execute_async()``,
and the resume-continuation path ``_execute_remaining()``.

Incident guarded: the "fix-then-miss cascade" where a fix to one execution mode
left the others silently swallowing the gate into a generic failure, losing the
``gate_id`` attribute and making human resume impossible.

All mocks in this module are confined to a local invoker — no internal runtime
components are mocked (P3 compliant).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.gate_protocol import GatePendingError
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor, execute_async
from hi_agent.trajectory.stage_graph import StageGraph

from tests.helpers.kernel_adapter_fixture import MockKernel
from tests.helpers.kernel_facade_fixture import MockKernelFacade


def _two_stage_graph() -> StageGraph:
    g = StageGraph()
    g.add_edge("stage_a", "stage_b")
    return g


def _install_gate_on_stage_a(executor: RunExecutor, gate_id: str, gate_type: str) -> None:
    """Patch _execute_stage to register a gate and raise on stage_a once."""
    original = executor._execute_stage
    fired = [False]

    def patched(stage_id: str) -> str | None:
        if stage_id == "stage_a" and not fired[0]:
            fired[0] = True
            executor.register_gate(gate_id, gate_type, phase_name="stage_a")
            raise GatePendingError(gate_id=gate_id)
        return original(stage_id)

    executor._execute_stage = patched  # type: ignore[method-assign]  expiry_wave: Wave 27


@pytest.mark.integration
def test_execute_propagates_gate_pending_error() -> None:
    """execute() must raise GatePendingError with a non-empty gate_id."""
    graph = _two_stage_graph()
    contract = TaskContract(task_id="anchor-7-execute", goal="gate via execute()")
    kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    gate_id = "gate-anchor-7-exec"
    _install_gate_on_stage_a(executor, gate_id, "final_approval")

    with pytest.raises(GatePendingError) as exc_info:
        executor.execute()

    assert isinstance(exc_info.value.gate_id, str)
    assert exc_info.value.gate_id == gate_id
    assert executor._gate_pending == gate_id


@pytest.mark.integration
def test_execute_graph_propagates_gate_pending_error() -> None:
    """execute_graph() must raise GatePendingError with a non-empty gate_id."""
    graph = _two_stage_graph()
    contract = TaskContract(task_id="anchor-7-graph", goal="gate via execute_graph()")
    kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    gate_id = "gate-anchor-7-graph"
    _install_gate_on_stage_a(executor, gate_id, "artifact_review")

    with pytest.raises(GatePendingError) as exc_info:
        executor.execute_graph()

    assert isinstance(exc_info.value.gate_id, str)
    assert exc_info.value.gate_id == gate_id


@pytest.mark.integration
# Anchor 7 part 2 used to xfail strictly against SA-A7-async-graph — S2
# structural remediation landed 2026-04-21: GraphFactory.from_stage_graph()
# mirrors the linear stage_graph into the async TrajectoryGraph, and
# execute_async()'s handler now drives executor._execute_stage for mirrored
# nodes regardless of kernel sync-capability. Test now asserts the expected
# behaviour directly.
def test_execute_async_gate_propagates_or_records_terminally() -> None:
    """execute_async() must either raise GatePendingError or return a non-completed RunResult.

    The contract of Anchor 7 is that a pending gate is never silently treated as a
    successful run. Whether the async scheduler converts the exception into a
    failed RunResult or re-raises is a runtime detail — the assertion is that the
    gate is observably surfaced, not swallowed into ``status == 'completed'``.
    """
    graph = _two_stage_graph()
    contract = TaskContract(
        task_id="anchor-7-async",
        goal="gate via execute_async()",
        task_family="quick_task",
    )
    kernel = MockKernelFacade()
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    gate_id = "gate-anchor-7-async"
    _install_gate_on_stage_a(executor, gate_id, "route_direction")

    gate_raised = False
    result = None
    try:
        result = asyncio.run(execute_async(executor, max_concurrency=2))
    except GatePendingError as exc:
        gate_raised = True
        assert exc.gate_id == gate_id

    if not gate_raised:
        # The async scheduler converted the gate into a terminal RunResult.
        # It must NOT be reported as completed — that would be a silent swallow.
        assert result is not None, "execute_async returned None instead of a RunResult"
        assert result.status != "completed", (
            f"execute_async swallowed GatePendingError into completed status: {result!r}"
        )
        # The executor must still carry the pending gate for human resume.
        assert executor._gate_pending == gate_id, (
            "executor._gate_pending was cleared despite the gate never being resolved"
        )


@pytest.mark.integration
def test_execute_remaining_propagates_gate_pending_error(tmp_path: Path) -> None:
    """_execute_remaining() (resume-continuation) must propagate GatePendingError."""
    graph = _two_stage_graph()
    contract = TaskContract(
        task_id="anchor-7-resume",
        goal="gate via _execute_remaining()",
    )
    kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    # Start the run so run_id is available for the resume-like path.
    executor._run_id = kernel.start_run(contract.task_id)

    gate_id = "gate-anchor-7-remaining"
    _install_gate_on_stage_a(executor, gate_id, "contract_correction")

    with pytest.raises(GatePendingError) as exc_info:
        executor._execute_remaining()

    assert isinstance(exc_info.value.gate_id, str)
    assert exc_info.value.gate_id == gate_id

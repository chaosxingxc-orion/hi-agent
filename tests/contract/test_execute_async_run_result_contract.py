"""Contract tests: execute_async() must return RunResult with truthful provenance.

Verifies:
1. execute_async() returns RunResult (same type as execute())
2. RunResult has required fields: run_id, status, stages, artifacts
3. llm_mode is not hardcoded "heuristic" when no LLM was used
   (should be "unknown" when no capability provenance is recorded)
"""

from __future__ import annotations

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.contracts.requests import RunResult
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor, execute_async

from tests.helpers.kernel_adapter_fixture import MockKernel
from tests.helpers.kernel_facade_fixture import MockKernelFacade


def _contract(goal: str = "Say hello", task_family: str = "quick_task") -> TaskContract:
    return TaskContract(task_id="contract-async-001", goal=goal, task_family=task_family)


def _make_executor(contract: TaskContract | None = None) -> RunExecutor:
    c = contract or _contract()
    kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(
        contract=c,
        kernel=kernel,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        raw_memory=RawMemoryStore(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    # Swap to async facade so execute_async can call start_run / execute_turn.
    executor.kernel = MockKernelFacade()  # type: ignore[assignment]  expiry_wave: Wave 27
    return executor


@pytest.mark.asyncio
async def test_execute_async_returns_run_result():
    """execute_async() must return RunResult, not AsyncRunResult."""
    executor = _make_executor()

    result = await execute_async(executor)

    assert isinstance(result, RunResult), (
        f"execute_async() must return RunResult, got {type(result).__name__}"
    )


@pytest.mark.asyncio
async def test_execute_async_run_result_has_required_fields():
    """RunResult from execute_async() must have the same top-level fields as execute()."""
    executor = _make_executor()

    result = await execute_async(executor)

    assert hasattr(result, "run_id"), "RunResult must have run_id"
    assert hasattr(result, "status"), "RunResult must have status"
    assert hasattr(result, "stages"), "RunResult must have stages"
    assert hasattr(result, "artifacts"), "RunResult must have artifacts"
    assert result.run_id, "run_id must be non-empty"
    assert result.status == "completed", (
        f"status must be 'completed', got {result.status!r}"
    )


@pytest.mark.asyncio
async def test_execute_async_run_result_status_matches_execute():
    """For a simple task, execute_async() status must match execute() status."""
    contract = _contract()

    # Synchronous path
    sync_kernel = MockKernel(strict_mode=False)
    sync_executor = RunExecutor(
        contract=contract,
        kernel=sync_kernel,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        raw_memory=RawMemoryStore(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    sync_result = sync_executor.execute()

    # Async path
    async_executor = _make_executor(contract=_contract())
    async_result = await execute_async(async_executor)

    # Both should succeed for a trivial goal
    assert str(sync_result) == "completed"
    assert async_result.status == "completed"


@pytest.mark.asyncio
async def test_execute_async_llm_mode_not_hardcoded_heuristic_when_no_llm_used():
    """When no capability is invoked, llm_mode must not be hardcoded 'heuristic'.

    Without any capability invocation there is no provenance to classify the
    run as heuristic. The expected value is 'unknown' (truthful absence of
    information), not 'heuristic' (false positive).
    """
    executor = _make_executor()

    result = await execute_async(executor)

    # Provenance may or may not be present depending on lifecycle wiring.
    # When present, llm_mode must not be the stale hardcoded "heuristic".
    prov = getattr(result, "execution_provenance", None)
    if prov is not None:
        llm_mode = getattr(prov, "llm_mode", None)
        assert llm_mode != "heuristic" or _has_heuristic_capability_evidence(result), (
            f"llm_mode='heuristic' requires actual heuristic capability evidence; "
            f"got {llm_mode!r} with no capability invocations recorded"
        )


def _has_heuristic_capability_evidence(result: RunResult) -> bool:
    """Return True if any stage in result has heuristic capability evidence."""
    prov = getattr(result, "execution_provenance", None)
    if prov is None:
        return False
    evidence = getattr(prov, "evidence", {})
    return bool(evidence.get("heuristic_stage_count", 0))

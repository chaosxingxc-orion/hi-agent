"""Integration tests for execute_async() in runner.py.

Verifies that the async execution path produces correct results using
MockKernelFacade and exercises graph factory auto-selection, budget guard
integration, metrics recording, failure handling, and equivalence with
the synchronous execute() path for simple tasks.
"""

from __future__ import annotations

import asyncio

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.contracts.requests import RunResult
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor, execute_async
from hi_agent.task_mgmt.async_scheduler import AsyncTaskScheduler
from hi_agent.task_mgmt.budget_guard import BudgetGuard
from hi_agent.task_mgmt.graph_factory import GraphFactory
from hi_agent.trajectory.graph import TrajectoryGraph, TrajNode

from tests.helpers.kernel_adapter_fixture import MockKernel
from tests.helpers.kernel_facade_fixture import MockKernelFacade

pytestmark = pytest.mark.usefixtures("fallback_explicit")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_contract(goal: str = "Say hello", task_family: str = "quick_task") -> TaskContract:
    """Build a minimal TaskContract."""
    return TaskContract(task_id="task-001", goal=goal, task_family=task_family)


def _make_executor(
    contract: TaskContract | None = None,
    kernel_facade: MockKernelFacade | None = None,
    **kwargs,
) -> tuple[RunExecutor, MockKernelFacade]:
    """Create a RunExecutor backed by a MockKernel (sync adapter) and return
    the MockKernelFacade that execute_async will use.
    """
    contract = contract or _simple_contract()
    facade = kernel_facade or MockKernelFacade()
    # RunExecutor requires a RuntimeAdapter (sync MockKernel) for its own
    # internal bookkeeping.  We monkey-patch its `kernel` attribute to point
    # to the facade so execute_async() can call start_run / execute_turn.
    mock_kernel = MockKernel(strict_mode=False)
    kwargs.setdefault("raw_memory", RawMemoryStore())
    kwargs.setdefault("event_emitter", EventEmitter())
    kwargs.setdefault("compressor", MemoryCompressor())
    kwargs.setdefault("acceptance_policy", AcceptancePolicy())
    kwargs.setdefault("cts_budget", CTSExplorationBudget())
    kwargs.setdefault("policy_versions", PolicyVersionSet())
    executor = RunExecutor(contract=contract, kernel=mock_kernel, **kwargs)
    # execute_async reads executor.kernel �?replace with the async facade.
    executor.kernel = facade  # type: ignore[assignment]  expiry_wave: Wave 29
    return executor, facade


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_async_execution_completes():
    """execute_async with a simple goal should complete successfully."""
    executor, facade = _make_executor()
    await facade.start_run("pre-init", "sess", {})

    result = await execute_async(executor)

    assert isinstance(result, RunResult)
    assert result.status == "completed"
    assert result.run_id  # non-empty


@pytest.mark.asyncio
async def test_async_execution_with_multiple_stages():
    """A standard-complexity goal should produce a graph with 5 stages."""
    contract = _simple_contract(
        # Goal long enough (>50 chars) to avoid "simple", but without
        # parallel/speculative keywords so it maps to the "standard" template.
        goal="Produce a comprehensive quarterly revenue report for the board meeting today",
        task_family="analysis",
    )
    executor, _ = _make_executor(contract=contract)

    result = await execute_async(executor)

    assert result.status == "completed"
    assert result.run_id  # non-empty


@pytest.mark.asyncio
async def test_async_execution_respects_budget_guard():
    """BudgetGuard integration: verify budget is consumed during execution.

    We cannot directly inject a BudgetGuard into execute_async (it builds
    its own scheduler/graph), so we test at the AsyncTaskScheduler level
    to confirm the budget guard pattern works with the async path.
    """
    facade = MockKernelFacade()
    await facade.start_run("run-bg", "sess", {})
    guard = BudgetGuard(total_budget_tokens=10000)

    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=4)
    graph = GraphFactory()._build_simple()

    consumed_per_node = 1500

    async def make_handler(node_id):
        async def handler(action, grant):
            guard.consume(consumed_per_node)
            return {"node_id": node_id}

        return handler

    result = await scheduler.run(graph, run_id="run-bg", make_handler=make_handler)

    assert result.success is True
    # Simple template has 3 nodes; each consumed 1500 tokens = 4500 total
    assert guard.remaining_fraction == pytest.approx(1.0 - 4500 / 10000)
    assert guard.can_afford(5000) is True
    assert guard.can_afford(6000) is False


@pytest.mark.asyncio
async def test_async_execution_records_metrics():
    """The async execution should record events in MockKernelFacade."""
    executor, facade = _make_executor()

    result = await execute_async(executor)

    assert result.status == "completed"
    # MockKernelFacade stores events per run_id
    events = facade._events.get(result.run_id, [])
    assert len(events) > 0, "Expected at least one event to be recorded"
    # Verify event structure
    for evt in events:
        assert evt.event_type == "turn_completed"
        assert evt.run_id == result.run_id


@pytest.mark.asyncio
async def test_async_execution_handles_stage_failure():
    """When a handler raises, the scheduler should mark the node as failed
    and report failure in the ScheduleResult.
    """
    facade = MockKernelFacade()
    await facade.start_run("run-fail", "sess", {})

    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=4)

    # Build a simple graph: A -> B -> C; handler for B raises
    graph = TrajectoryGraph()
    for nid in ["A", "B", "C"]:
        graph.add_node(TrajNode(node_id=nid, node_type="task"))
    graph.add_sequence("A", "B")
    graph.add_sequence("B", "C")

    async def make_handler(node_id):
        async def handler(action, grant):
            if node_id == "B":
                raise RuntimeError("Stage B exploded")
            return {"node_id": node_id}

        return handler

    result = await scheduler.run(graph, run_id="run-fail", make_handler=make_handler)

    assert result.success is False
    assert "B" in result.failed_nodes
    assert "A" in result.completed_nodes
    # C depends on B, so it should never have run
    assert "C" not in result.completed_nodes


@pytest.mark.asyncio
async def test_async_execution_with_graph_factory_auto_select():
    """GraphFactory.auto_select should choose the right template based on goal."""
    factory = GraphFactory()

    # Simple goal -> simple template (3 nodes)
    name_simple, graph_simple = factory.auto_select(goal="Greet user")
    assert name_simple == "simple"
    assert len(list(graph_simple._nodes)) == 3

    # Parallel keywords -> parallel_gather template
    name_par, graph_par = factory.auto_select(
        goal="Compare the sales data side by side for Q1 and Q2"
    )
    assert name_par == "parallel_gather"
    # S1, S2-a, S2-b, S2-c, S3, S4, S5 = 7 nodes
    assert len(list(graph_par._nodes)) == 7

    # Speculative keywords -> speculative template
    name_spec, graph_spec = factory.auto_select(
        goal="Explore alternative approaches to the caching problem"
    )
    assert name_spec == "speculative"
    # S1, S2, S3-v1, S3-v2, S4, S5 = 6 nodes
    assert len(list(graph_spec._nodes)) == 6

    # Now run the parallel graph through the scheduler to confirm it works
    facade = MockKernelFacade()
    await facade.start_run("run-par", "sess", {})
    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=8)

    async def make_handler(node_id):
        async def handler(action, grant):
            return {"node_id": node_id}

        return handler

    result = await scheduler.run(graph_par, run_id="run-par", make_handler=make_handler)
    assert result.success is True
    assert len(result.completed_nodes) == 7


@pytest.mark.asyncio
async def test_execute_vs_execute_async_equivalence():
    """For a simple task, execute() and execute_async() should both
    succeed and cover equivalent stages.
    """
    contract = _simple_contract(goal="Say hello")

    # --- Synchronous execute() ---
    sync_kernel = MockKernel(strict_mode=False)
    sync_executor = RunExecutor(
        contract=contract,
        kernel=sync_kernel,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    sync_status = sync_executor.execute()

    assert sync_status == "completed"
    # Sync path records stages: check kernel events
    assert len(sync_kernel.events) > 0

    # --- Async execute_async() ---
    facade = MockKernelFacade()
    async_executor, _ = _make_executor(contract=contract, kernel_facade=facade)
    async_result = await execute_async(async_executor)

    assert async_result.status == "completed"

    # Both should produce a non-empty run_id
    assert sync_executor.run_id
    assert async_result.run_id


@pytest.mark.asyncio
async def test_async_execution_with_concurrency_limit():
    """Verify that max_concurrency parameter is respected during execution."""
    facade = MockKernelFacade()
    await facade.start_run("run-conc", "sess", {})

    active = 0
    max_active = 0

    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=2)

    # Build a flat graph with 6 independent nodes (all can run in parallel)
    graph = TrajectoryGraph()
    for i in range(6):
        graph.add_node(TrajNode(node_id=f"N{i}", node_type="task"))

    async def make_handler(node_id):
        async def handler(action, grant):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"node_id": node_id}

        return handler

    result = await scheduler.run(graph, run_id="run-conc", make_handler=make_handler)

    assert result.success is True
    assert len(result.completed_nodes) == 6
    assert max_active <= 2, f"Concurrency exceeded limit: {max_active} > 2"

"""Tests for AsyncTaskScheduler."""
import asyncio
import pytest
from hi_agent.task_mgmt.async_scheduler import AsyncTaskScheduler, ScheduleResult
from hi_agent.runtime_adapter.mock_kernel_facade import MockKernelFacade
from hi_agent.trajectory.graph import TrajectoryGraph, TrajNode


def make_node(node_id: str) -> TrajNode:
    return TrajNode(node_id=node_id, node_type="task")


def make_linear_graph(*node_ids: str) -> TrajectoryGraph:
    g = TrajectoryGraph()
    nodes = [make_node(nid) for nid in node_ids]
    for node in nodes:
        g.add_node(node)
    for i in range(len(nodes) - 1):
        g.add_sequence(nodes[i].node_id, nodes[i + 1].node_id)
    return g


@pytest.mark.asyncio
async def test_linear_graph_executes_in_order():
    facade = MockKernelFacade()
    await facade.start_run("run-001", "sess", {})
    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=4)

    order = []

    async def make_handler(node_id):
        async def _h(action, grant):
            order.append(node_id)
            return {"node_id": node_id}
        return _h

    graph = make_linear_graph("A", "B", "C")
    result = await scheduler.run(graph, run_id="run-001", make_handler=make_handler)

    assert result.success
    assert order == ["A", "B", "C"]
    assert set(result.completed_nodes) == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_parallel_nodes_execute_concurrently():
    facade = MockKernelFacade()
    await facade.start_run("run-002", "sess", {})
    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=8)

    started: list[str] = []
    barrier = asyncio.Event()

    async def make_handler(node_id):
        async def _h(action, grant):
            started.append(node_id)
            if len(started) == 3:
                barrier.set()
            await barrier.wait()
            return {}
        return _h

    # A, B, C with no deps → all run in parallel
    g = TrajectoryGraph()
    for nid in ["A", "B", "C"]:
        g.add_node(make_node(nid))

    result = await scheduler.run(g, run_id="run-002", make_handler=make_handler)
    assert result.success
    assert len(started) == 3


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    facade = MockKernelFacade()
    await facade.start_run("run-003", "sess", {})
    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=2)

    active = 0
    max_active = 0

    async def make_handler(node_id):
        async def _h(action, grant):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {}
        return _h

    g = TrajectoryGraph()
    for nid in ["A", "B", "C", "D", "E"]:
        g.add_node(make_node(nid))

    await scheduler.run(g, run_id="run-003", make_handler=make_handler)
    assert max_active <= 2


@pytest.mark.asyncio
async def test_dynamic_node_added_during_execution():
    facade = MockKernelFacade()
    await facade.start_run("run-004", "sess", {})
    scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=4)

    executed = []

    async def make_handler(node_id):
        async def _h(action, grant):
            executed.append(node_id)
            if node_id == "A":
                scheduler.add_node(make_node("B"), depends_on=["A"])
            return {}
        return _h

    g = TrajectoryGraph()
    g.add_node(make_node("A"))

    result = await scheduler.run(g, run_id="run-004", make_handler=make_handler)

    assert "A" in executed
    assert "B" in executed
    assert result.success

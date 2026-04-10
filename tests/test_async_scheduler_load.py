"""Load and stress tests for AsyncTaskScheduler."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from hi_agent.task_mgmt.async_scheduler import AsyncTaskScheduler, ScheduleResult
from hi_agent.trajectory.graph import TrajectoryGraph, TrajNode


def _make_node(node_id: str) -> TrajNode:
    return TrajNode(node_id=node_id, node_type="task", payload={})


def _make_mock_kernel(sleep_time: float = 0.001):
    """Create a mock kernel whose execute_turn sleeps briefly."""
    kernel = MagicMock()

    async def fake_turn(**kwargs):
        await asyncio.sleep(sleep_time)
        return {"ok": True}

    kernel.execute_turn = AsyncMock(side_effect=fake_turn)
    return kernel


async def _make_handler(node_id: str):
    """Default handler factory."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_100_independent_nodes():
    """100 independent nodes with concurrency=10 should finish quickly."""
    graph = TrajectoryGraph()
    for i in range(100):
        graph.add_node(_make_node(f"n{i}"))

    kernel = _make_mock_kernel(0.001)
    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=10)
    start = time.monotonic()
    result = await scheduler.run(graph, run_id="r1", make_handler=_make_handler)
    elapsed = time.monotonic() - start
    assert result.success
    assert len(result.completed_nodes) == 100
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_100_chain():
    """100 nodes in a chain (sequential dependencies)."""
    graph = TrajectoryGraph()
    for i in range(100):
        graph.add_node(_make_node(f"n{i}"))
    for i in range(99):
        graph.add_sequence(f"n{i}", f"n{i + 1}")

    kernel = _make_mock_kernel(0.001)
    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=10)
    result = await scheduler.run(graph, run_id="r2", make_handler=_make_handler)
    assert result.success
    assert len(result.completed_nodes) == 100


@pytest.mark.asyncio
async def test_diamond_graph():
    """Diamond: A -> {B, C} -> D."""
    graph = TrajectoryGraph()
    for nid in ["A", "B", "C", "D"]:
        graph.add_node(_make_node(nid))
    graph.add_sequence("A", "B")
    graph.add_sequence("A", "C")
    graph.add_sequence("B", "D")
    graph.add_sequence("C", "D")

    kernel = _make_mock_kernel(0.001)
    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=4)
    result = await scheduler.run(graph, run_id="r3", make_handler=_make_handler)
    assert result.success
    assert set(result.completed_nodes) == {"A", "B", "C", "D"}


@pytest.mark.asyncio
async def test_500_independent():
    """500 independent nodes with concurrency=20, should finish under 3s."""
    graph = TrajectoryGraph()
    for i in range(500):
        graph.add_node(_make_node(f"n{i}"))

    kernel = _make_mock_kernel(0.001)
    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=20)
    start = time.monotonic()
    result = await scheduler.run(graph, run_id="r4", make_handler=_make_handler)
    elapsed = time.monotonic() - start
    assert result.success
    assert len(result.completed_nodes) == 500
    assert elapsed < 3.0


@pytest.mark.asyncio
async def test_backpressure():
    """Max concurrent tasks should never exceed the concurrency limit."""
    max_concurrency = 5
    concurrent_counter = {"current": 0, "peak": 0}
    lock = asyncio.Lock()

    kernel = MagicMock()

    async def counting_turn(**kwargs):
        async with lock:
            concurrent_counter["current"] += 1
            concurrent_counter["peak"] = max(
                concurrent_counter["peak"], concurrent_counter["current"]
            )
        await asyncio.sleep(0.01)
        async with lock:
            concurrent_counter["current"] -= 1
        return {"ok": True}

    kernel.execute_turn = AsyncMock(side_effect=counting_turn)

    graph = TrajectoryGraph()
    for i in range(30):
        graph.add_node(_make_node(f"n{i}"))

    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=max_concurrency)
    result = await scheduler.run(graph, run_id="r5", make_handler=_make_handler)
    assert result.success
    assert concurrent_counter["peak"] <= max_concurrency


@pytest.mark.asyncio
async def test_dynamic_addition():
    """Dynamically add a node during execution."""
    graph = TrajectoryGraph()
    graph.add_node(_make_node("root"))

    kernel = _make_mock_kernel(0.001)
    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=4)

    added = False

    async def handler_factory(node_id: str):
        nonlocal added
        handler = AsyncMock()
        if node_id == "root" and not added:
            added = True
            scheduler.add_node(_make_node("dynamic"), depends_on=["root"])
        return handler

    result = await scheduler.run(graph, run_id="r6", make_handler=handler_factory)
    assert result.success
    assert "root" in result.completed_nodes


@pytest.mark.asyncio
async def test_failure_propagation():
    """A failing node should appear in failed_nodes."""
    graph = TrajectoryGraph()
    graph.add_node(_make_node("ok"))
    graph.add_node(_make_node("fail"))

    kernel = MagicMock()

    async def fail_turn(**kwargs):
        nid = kwargs.get("action", MagicMock()).action_id
        if nid == "fail":
            raise RuntimeError("boom")
        await asyncio.sleep(0.001)
        return {"ok": True}

    kernel.execute_turn = AsyncMock(side_effect=fail_turn)
    scheduler = AsyncTaskScheduler(kernel=kernel, max_concurrency=4)
    result = await scheduler.run(graph, run_id="r7", make_handler=_make_handler)
    assert not result.success
    assert "fail" in result.failed_nodes

"""Integration tests for async execution via AsyncTaskScheduler + MockKernelFacade."""
import asyncio
import pytest
from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import TaskContract, deterministic_id
from hi_agent.runner import RunExecutor, execute_async
from tests.helpers.kernel_facade_fixture import MockKernelFacade


@pytest.fixture
def contract():
    return TaskContract(
        task_id=deterministic_id("task"),
        goal="Analyze test data",
        task_family="analysis",
    )


@pytest.mark.asyncio
async def test_run_executor_uses_async_scheduler(contract):
    kernel = MockKernelFacade()
    executor = RunExecutor(contract=contract, kernel=kernel)

    result = await execute_async(executor, max_concurrency=4)

    assert result is not None
    assert result.run_id is not None
    assert result.success


@pytest.mark.asyncio
async def test_multiple_concurrent_runs():
    """50 concurrent runs complete without deadlock."""
    kernel = MockKernelFacade()

    async def run_one(i: int):
        contract = TaskContract(
            task_id=deterministic_id(f"task-{i}"),
            goal=f"Goal {i}",
            task_family="test",
        )
        executor = RunExecutor(contract=contract, kernel=kernel)
        return await execute_async(executor, max_concurrency=16)

    results = await asyncio.gather(*[run_one(i) for i in range(50)])
    assert all(r is not None for r in results)
    assert all(r.success for r in results)

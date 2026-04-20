# tests/test_kernel_facade_inprocess.py
import asyncio

import pytest
from agent_kernel.kernel.contracts import Action
from hi_agent.runtime_adapter.kernel_facade_adapter import create_local_adapter

from tests.helpers.kernel_facade_fixture import MockKernelFacade


@pytest.mark.asyncio
async def test_execute_turn_returns_result():
    facade = MockKernelFacade()
    action = Action(
        action_id="act-001",
        run_id="run-001",
        action_type="trace_stage",
        effect_class="read_only",
        input_json={"node_id": "S1"},
    )

    async def handler(action, sandbox_grant):
        return {"output": "done"}

    result = await facade.execute_turn(
        run_id="run-001",
        action=action,
        handler=handler,
        idempotency_key="S1:0",
    )
    assert result.outcome_kind == "dispatched"


@pytest.mark.asyncio
async def test_subscribe_events_yields_after_execute():
    facade = MockKernelFacade()
    action = Action(
        action_id="act-002",
        run_id="run-002",
        action_type="trace_stage",
        effect_class="read_only",
    )
    events = []

    async def collect():
        async for event in facade.subscribe_events("run-002"):
            events.append(event)
            break  # collect one then stop

    async def execute():
        await asyncio.sleep(0.01)
        async def simple_handler(a, s):
            return {"output": "ok"}
        await facade.execute_turn(
            run_id="run-002",
            action=action,
            handler=simple_handler,
            idempotency_key="S1:0",
        )

    await asyncio.gather(collect(), execute())
    assert len(events) == 1
    assert events[0].run_id == "run-002"


class TestAsyncChildRunMethods:
    """Tests for KernelFacadeAdapter.spawn_child_run_async and query_child_runs_async."""

    @pytest.mark.asyncio
    async def test_spawn_child_run_async_returns_non_empty_string(self):
        adapter = create_local_adapter()
        parent_run_id = adapter.start_run("task-parent-001")
        child_run_id = await adapter.spawn_child_run_async(parent_run_id, "task-child-001")
        assert isinstance(child_run_id, str)
        assert child_run_id.strip() != ""

    @pytest.mark.asyncio
    async def test_query_child_runs_async_returns_list(self):
        adapter = create_local_adapter()
        parent_run_id = adapter.start_run("task-parent-002")
        await adapter.spawn_child_run_async(parent_run_id, "task-child-002")
        result = await adapter.query_child_runs_async(parent_run_id)
        assert isinstance(result, list)

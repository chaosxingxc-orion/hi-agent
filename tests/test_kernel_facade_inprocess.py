# tests/test_kernel_facade_inprocess.py
import asyncio
import pytest
from tests.helpers.kernel_facade_fixture import MockKernelFacade
from agent_kernel.kernel.contracts import Action


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

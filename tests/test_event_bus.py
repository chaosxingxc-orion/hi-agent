import asyncio
import pytest
from hi_agent.server.event_bus import EventBus
from agent_kernel.kernel.contracts import RuntimeEvent


def make_event(run_id: str, offset: int = 1) -> RuntimeEvent:
    return RuntimeEvent(
        run_id=run_id,
        event_id=f"{run_id}:{offset}",
        commit_offset=offset,
        event_type="turn_completed",
        event_class="fact",
        event_authority="authoritative_fact",
        ordering_key=f"key:{offset}",
        wake_policy="projection_only",
        created_at="2026-04-08T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    bus = EventBus()
    q = bus.subscribe("run-001")

    event = make_event("run-001")
    bus.publish(event)

    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received.run_id == "run-001"


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    bus = EventBus()
    q1 = bus.subscribe("run-002")
    q2 = bus.subscribe("run-002")

    bus.publish(make_event("run-002"))

    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert r1.run_id == r2.run_id == "run-002"


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving():
    bus = EventBus()
    q = bus.subscribe("run-003")
    bus.unsubscribe("run-003", q)

    bus.publish(make_event("run-003"))
    assert q.empty()

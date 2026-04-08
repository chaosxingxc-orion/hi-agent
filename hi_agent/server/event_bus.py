"""Process-local asyncio.Queue fan-out for SSE streaming.

Usage:
    bus = EventBus()

    # In execute_turn wrapper:
    bus.publish(event)

    # In SSE endpoint:
    q = bus.subscribe(run_id)
    try:
        async for event in stream_queue(q):
            yield event
    finally:
        bus.unsubscribe(run_id, q)
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from agent_kernel.kernel.contracts import RuntimeEvent


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[RuntimeEvent]]] = defaultdict(list)

    def publish(self, event: RuntimeEvent) -> None:
        for q in self._queues.get(event.run_id, []):
            q.put_nowait(event)

    def subscribe(self, run_id: str) -> asyncio.Queue[RuntimeEvent]:
        q: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._queues[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[RuntimeEvent]) -> None:
        queues = self._queues.get(run_id, [])
        if q in queues:
            queues.remove(q)


# Module-level singleton — imported by routes and by execute_turn wrapper
event_bus = EventBus()

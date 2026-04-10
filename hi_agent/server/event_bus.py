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
    """EventBus with bounded queues and backpressure handling."""

    def __init__(self, max_queue_size: int = 1000) -> None:
        """Initialize EventBus.

        Args:
            max_queue_size: Maximum number of events buffered per subscriber.
                When a subscriber's queue is full, the oldest event is dropped.
        """
        self._max_queue_size = max_queue_size
        self._queues: dict[str, list[asyncio.Queue[RuntimeEvent]]] = defaultdict(list)
        self._total_published: int = 0
        self._total_dropped: int = 0

    def publish(self, event: RuntimeEvent) -> None:
        """Publish an event to all subscribers for the event's run_id.

        If a subscriber's queue is full, the oldest event is dropped to make
        room for the new one.
        """
        for q in self._queues.get(event.run_id, []):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._total_dropped += 1
            q.put_nowait(event)
            self._total_published += 1

    def subscribe(self, run_id: str) -> asyncio.Queue[RuntimeEvent]:
        """Create a bounded queue for a new subscriber and return it."""
        q: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=self._max_queue_size)
        self._queues[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[RuntimeEvent]) -> None:
        """Remove a subscriber queue."""
        queues = self._queues.get(run_id, [])
        if q in queues:
            queues.remove(q)
        # Clean up empty run_id entries
        if run_id in self._queues and not self._queues[run_id]:
            del self._queues[run_id]

    def get_stats(self) -> dict[str, int]:
        """Return bus statistics.

        Returns:
            Dictionary with subscriber_count, total_published, total_dropped.
        """
        subscriber_count = sum(len(qs) for qs in self._queues.values())
        return {
            "subscriber_count": subscriber_count,
            "total_published": self._total_published,
            "total_dropped": self._total_dropped,
        }


# Module-level singleton — imported by routes and by execute_turn wrapper
event_bus = EventBus()

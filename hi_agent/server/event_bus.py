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
import logging
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)

from agent_kernel.kernel.contracts import RuntimeEvent


class EventBus:
    """EventBus with bounded queues and backpressure handling.

    Thread-safety model
    -------------------
    ``subscribe``/``unsubscribe`` must be called from the asyncio event loop
    thread (they capture ``asyncio.get_running_loop()``).  ``publish`` may be
    called from **any** thread: when called from outside the loop it uses
    ``loop.call_soon_threadsafe`` so all queue mutations always execute in the
    loop thread.
    """

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
        # Protects _queues dict mutations (subscribe/unsubscribe).
        self._lock = threading.Lock()
        # Captured lazily on first subscribe; used by cross-thread publish.
        self._loop: asyncio.AbstractEventLoop | None = None

    def _put_nowait_in_loop(self, q: asyncio.Queue[RuntimeEvent], event: RuntimeEvent) -> None:
        """Enqueue one event into *q*.  Must be called from the loop thread."""
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._total_dropped += 1
        q.put_nowait(event)
        self._total_published += 1

    def publish(self, event: RuntimeEvent) -> None:
        """Publish an event to all subscribers for the event's run_id.

        Safe to call from any thread.  When called from the asyncio loop thread
        events are enqueued directly; when called from a different thread they
        are scheduled via ``loop.call_soon_threadsafe`` so that queue mutations
        always happen inside the loop.

        If a subscriber's queue is full, the oldest event is dropped to make
        room for the new one.
        """
        with self._lock:
            queues = list(self._queues.get(event.run_id, []))

        if not queues:
            return

        # Determine whether we are already running inside the captured loop.
        try:
            current_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is not None and current_loop is self._loop:
            # Called from the loop thread — direct enqueue is safe.
            for q in queues:
                self._put_nowait_in_loop(q, event)
        elif self._loop is not None and not self._loop.is_closed():
            # Called from a foreign thread — schedule in the loop thread.
            for q in queues:
                self._loop.call_soon_threadsafe(self._put_nowait_in_loop, q, event)
        else:
            # No event loop captured: synchronous context (tests, CLI callers).
            # Fall back to direct put_nowait — safe when running single-threaded
            # or in a pure-sync environment without asyncio.
            for q in queues:
                self._put_nowait_in_loop(q, event)

    def subscribe(self, run_id: str) -> asyncio.Queue[RuntimeEvent]:
        """Create a bounded queue for a new subscriber and return it.

        Must be called from within a running asyncio event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
        except RuntimeError:
            logger.debug("subscribe() called outside running event loop; loop will be captured on first publish")
        q: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._queues[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[RuntimeEvent]) -> None:
        """Remove a subscriber queue."""
        with self._lock:
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
        with self._lock:
            subscriber_count = sum(len(qs) for qs in self._queues.values())
        return {
            "subscriber_count": subscriber_count,
            "total_published": self._total_published,
            "total_dropped": self._total_dropped,
        }


# Module-level singleton — imported by routes and by execute_turn wrapper
event_bus = EventBus()

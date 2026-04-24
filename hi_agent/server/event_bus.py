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
import json
import logging
import threading
import uuid
from collections import defaultdict

logger = logging.getLogger(__name__)

import contextlib

from hi_agent.runtime_adapter import RuntimeEvent
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent


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

    def __init__(
        self,
        max_queue_size: int = 1000,
        event_store: SQLiteEventStore | None = None,
    ) -> None:
        """Initialize EventBus.

        Args:
            max_queue_size: Maximum number of events buffered per subscriber.
                When a subscriber's queue is full, the oldest event is dropped.
            event_store: Optional durable store.  When provided, every event is
                persisted *before* being enqueued so that SSE clients can replay
                missed events via ``Last-Event-ID``.  When ``None`` (default)
                behaviour is identical to the pre-store implementation.
        """
        self._max_queue_size = max_queue_size
        self._event_store: SQLiteEventStore | None = event_store
        self._queues: dict[str, list[asyncio.Queue[RuntimeEvent]]] = defaultdict(list)
        self._total_published: int = 0
        self._total_dropped: int = 0
        # Protects _queues dict mutations (subscribe/unsubscribe).
        self._lock = threading.Lock()
        # Captured lazily on first subscribe; used by cross-thread publish.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Sync observers: called best-effort on every publish() from any thread.
        # Used by threading-based components (e.g. RunManager) that cannot use asyncio queues.
        self._sync_observers: list = []

    def _put_nowait_in_loop(self, q: asyncio.Queue[RuntimeEvent], event: RuntimeEvent) -> None:
        """Enqueue one event into *q*.  Must be called from the loop thread."""
        if q.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                q.get_nowait()
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
        # --- Durable persistence (before fan-out) ---
        if self._event_store is not None:
            payload_str: str
            if event.payload_json is None:
                payload_str = ""
            elif isinstance(event.payload_json, str):
                payload_str = event.payload_json
            else:
                payload_str = json.dumps(event.payload_json)
            stored = StoredEvent(
                event_id=event.event_id or str(uuid.uuid4()),
                run_id=event.run_id,
                sequence=event.commit_offset or 0,
                event_type=event.event_type,
                payload_json=payload_str,
            )
            self._event_store.append(stored)
            logger.debug(
                "event.published run_id=%s event_type=%s sequence=%d tenant_id=%s",
                event.run_id,
                event.event_type,
                event.commit_offset or 0,
                "",
            )

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

        # Notify sync observers (e.g. RunManager) — best-effort, never raises.
        with self._lock:
            observers = list(self._sync_observers)
        for obs in observers:
            with contextlib.suppress(Exception):
                obs(event)

    def add_sync_observer(self, callback) -> None:
        """Register a thread-safe sync callback invoked on every publish().

        Used by threading-based components (e.g. RunManager) that cannot use
        asyncio Queue subscriptions.  Callbacks are called best-effort; any
        exception is silently suppressed to avoid disrupting event fan-out.
        """
        with self._lock:
            self._sync_observers.append(callback)

    def subscribe(self, run_id: str) -> asyncio.Queue[RuntimeEvent]:
        """Create a bounded queue for a new subscriber and return it.

        Must be called from within a running asyncio event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
        except RuntimeError:
            logger.debug(
                "subscribe() called outside running event loop; loop will be "
                "captured on first publish"
            )
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

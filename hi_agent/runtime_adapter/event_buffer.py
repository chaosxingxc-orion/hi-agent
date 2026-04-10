"""Buffer events when kernel is temporarily unreachable.

Events are stored in-memory with bounded capacity and flushed
when the connection to the kernel restores.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any


class EventBuffer:
    """Buffers events when kernel is temporarily unreachable.

    Events are stored in-memory and flushed when connection restores.
    Has a max size to prevent unbounded growth. Thread-safe.
    """

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize buffer with bounded capacity.

        Args:
            max_size: Maximum number of events to buffer. When full,
                oldest events are dropped on new appends.
        """
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max_size = max_size
        self._buffer: deque[tuple[str, dict[str, Any]]] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._dropped_count = 0

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append an event to the buffer.

        If the buffer is full, the oldest event is silently dropped.

        Args:
            event_type: Type identifier for the event.
            payload: Event payload dictionary.
        """
        with self._lock:
            was_full = len(self._buffer) == self._max_size
            self._buffer.append((event_type, dict(payload)))
            if was_full:
                self._dropped_count += 1

    def flush(self, target: Callable[[str, dict[str, Any]], None]) -> int:
        """Flush all buffered events to target callable.

        Events are delivered in FIFO order. The buffer is cleared
        after all events are delivered. If target raises, remaining
        events stay in buffer.

        Args:
            target: Callable receiving (event_type, payload) for each event.

        Returns:
            Number of events successfully flushed.
        """
        with self._lock:
            snapshot = list(self._buffer)
            self._buffer.clear()

        flushed = 0
        remaining: list[tuple[str, dict[str, Any]]] = []
        for event_type, payload in snapshot:
            try:
                target(event_type, payload)
                flushed += 1
            except Exception:
                remaining.append((event_type, payload))
                # Keep all subsequent events too
                remaining.extend(snapshot[flushed + len(remaining):])
                break

        if remaining:
            with self._lock:
                # Prepend remaining back (they are older than any new appends)
                for item in reversed(remaining):
                    self._buffer.appendleft(item)

        return flushed

    def size(self) -> int:
        """Return current number of buffered events."""
        with self._lock:
            return len(self._buffer)

    def is_full(self) -> bool:
        """Return True if buffer has reached max capacity."""
        with self._lock:
            return len(self._buffer) == self._max_size

    def clear(self) -> None:
        """Discard all buffered events."""
        with self._lock:
            self._buffer.clear()

    @property
    def dropped_count(self) -> int:
        """Total number of events dropped due to capacity overflow."""
        with self._lock:
            return self._dropped_count

    @property
    def max_size(self) -> int:
        """Maximum buffer capacity."""
        return self._max_size

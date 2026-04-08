"""Task communication: notifications, signals, and messages.

Inspired by:
- claude-code task-notification XML protocol
- Temporal signal/query mechanism
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class TaskNotification:
    """Notification sent when a task changes state."""

    task_id: str
    event: str           # started, completed, failed, yielded, resumed, progress
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    # For completion:
    result: Any = None
    tokens_used: int = 0
    duration_ms: int = 0


@dataclass
class TaskSignal:
    """Signal sent to a running/yielded task."""

    signal_type: str     # resume, cancel, update_priority, inject_data
    target_task_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_task_id: str = ""


class TaskCommunicator:
    """Task-to-task communication hub."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = {}       # event_type -> [callbacks]
        self._task_subscribers: dict[str, list[Callable]] = {}  # task_id -> [callbacks]
        self._message_log: list[TaskNotification | TaskSignal] = []
        self._signal_queue: dict[str, list[TaskSignal]] = {}    # task_id -> pending signals

    def notify(self, notification: TaskNotification) -> None:
        """Broadcast a task notification.

        All subscribers for event type and task_id are called.
        """
        if not notification.timestamp:
            notification.timestamp = datetime.now(timezone.utc).isoformat()
        self._message_log.append(notification)

        # Fire event-type subscribers
        for cb in self._subscribers.get(notification.event, []):
            cb(notification)

        # Fire task-specific subscribers
        for cb in self._task_subscribers.get(notification.task_id, []):
            cb(notification)

    def send_signal(self, signal: TaskSignal) -> None:
        """Send a signal to a specific task. Queued if task is yielded."""
        self._message_log.append(signal)
        self._signal_queue.setdefault(signal.target_task_id, []).append(signal)

    def subscribe_event(self, event_type: str, callback: Callable) -> None:
        """Subscribe to all notifications of a given event type."""
        self._subscribers.setdefault(event_type, []).append(callback)

    def subscribe_task(self, task_id: str, callback: Callable) -> None:
        """Subscribe to all notifications for a specific task."""
        self._task_subscribers.setdefault(task_id, []).append(callback)

    def get_pending_signals(self, task_id: str) -> list[TaskSignal]:
        """Get and drain pending signals for a task (e.g., on resume)."""
        signals = self._signal_queue.pop(task_id, [])
        return signals

    def broadcast(self, source_task_id: str, event: str, payload: dict) -> None:
        """Broadcast to all subscribers (event-type and all task subscribers)."""
        notification = TaskNotification(
            task_id=source_task_id,
            event=event,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._message_log.append(notification)

        # Fire event-type subscribers
        for cb in self._subscribers.get(event, []):
            cb(notification)

        # Fire ALL task subscribers (broadcast reaches everyone)
        for task_id, callbacks in self._task_subscribers.items():
            for cb in callbacks:
                cb(notification)

    def get_log(self) -> list[TaskNotification | TaskSignal]:
        """Return the full message log."""
        return list(self._message_log)

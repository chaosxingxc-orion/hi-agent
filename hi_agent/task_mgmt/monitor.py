"""Task monitor: heartbeat, progress tracking, and deadlock detection."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hi_agent.task_mgmt.handle import TaskHandle, TaskStatus


@dataclass
class RecoveryReport:
    """Summary of automatic recovery actions taken."""

    stuck_recovered: int = 0
    deadlocks_broken: int = 0
    actions_taken: list[str] = field(default_factory=list)


class TaskMonitor:
    """Observes task execution health."""

    def __init__(
        self,
        heartbeat_timeout_seconds: int = 300,
        on_stuck: Callable[[str, str], None] | None = None,
        on_deadlock: Callable[[list[str]], None] | None = None,
        auto_recover: bool = False,
    ) -> None:
        """Initialize TaskMonitor.

        Args:
            heartbeat_timeout_seconds: Seconds before a task is considered stuck.
            on_stuck: Optional callback invoked for each stuck task (task_id, reason).
            on_deadlock: Optional callback invoked for each deadlock cycle (list of task_ids).
            auto_recover: When True and no callback is set, automatically recover
                (mark stuck tasks failed, abort youngest task in deadlock cycles).
        """
        self._heartbeats: dict[str, float] = {}
        self._progress: dict[str, dict] = {}
        self._events: list[dict] = []
        self._timeout = heartbeat_timeout_seconds
        self.on_stuck = on_stuck
        self.on_deadlock = on_deadlock
        self.auto_recover = auto_recover

    def heartbeat(self, task_id: str, progress: dict | None = None) -> None:
        """Record heartbeat from a running task."""
        self._heartbeats[task_id] = time.monotonic()
        if progress is not None:
            self._progress[task_id] = progress
        self.record_event(task_id, "heartbeat", progress)

    def get_progress(self, task_id: str) -> dict | None:
        """Return progress info for `task_id`, or None."""
        return self._progress.get(task_id)

    def detect_stuck(self) -> list[str]:
        """Find tasks that have not sent a heartbeat within timeout."""
        now = time.monotonic()
        return [
            task_id
            for task_id, last_hb in self._heartbeats.items()
            if now - last_hb > self._timeout
        ]

    def detect_deadlock(self, tasks: dict[str, TaskHandle]) -> list[list[str]]:
        """Detect circular dependency chains among active tasks."""
        adj: dict[str, list[str]] = {}
        active_ids: set[str] = set()
        for task_id, task_handle in tasks.items():
            if task_handle.is_terminal():
                continue
            active_ids.add(task_id)
            adj[task_id] = [
                blocked_id
                for blocked_id in task_handle.blocked_by
                if blocked_id in tasks and not tasks[blocked_id].is_terminal()
            ]

        white, gray, black = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(active_ids, white)
        parent: dict[str, str | None] = dict.fromkeys(active_ids)
        cycles: list[list[str]] = []

        def _dfs(node_id: str) -> None:
            color[node_id] = gray
            for neighbor in adj.get(node_id, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == gray:
                    cycle: list[str] = [neighbor]
                    current = node_id
                    while current != neighbor:
                        cycle.append(current)
                        current = parent.get(current, neighbor)  # type: ignore[assignment]  expiry_wave: Wave 17
                    cycle.append(neighbor)
                    cycle.reverse()
                    cycles.append(cycle)
                elif color[neighbor] == white:
                    parent[neighbor] = node_id
                    _dfs(neighbor)
            color[node_id] = black

        for task_id in active_ids:
            if color.get(task_id, white) == white:
                _dfs(task_id)

        return cycles

    def check_and_recover(self, tasks: dict[str, TaskHandle]) -> RecoveryReport:
        """Detect stuck tasks and deadlocks, then invoke callbacks or auto-recover.

        Args:
            tasks: Current task map (same format as ``detect_deadlock``).

        Returns:
            A ``RecoveryReport`` summarising all actions taken.
        """
        report = RecoveryReport()

        # --- stuck tasks ---
        stuck_ids = self.detect_stuck()
        for task_id in stuck_ids:
            reason = f"No heartbeat for >{self._timeout}s"
            if self.on_stuck is not None:
                self.on_stuck(task_id, reason)
                report.actions_taken.append(f"on_stuck callback for {task_id}")
                report.stuck_recovered += 1
            elif self.auto_recover and task_id in tasks:
                tasks[task_id].status = TaskStatus.FAILED
                tasks[task_id].error = reason
                report.stuck_recovered += 1
                report.actions_taken.append(f"auto-failed stuck task {task_id}")

        # --- deadlocks ---
        cycles = self.detect_deadlock(tasks)
        for cycle in cycles:
            if self.on_deadlock is not None:
                # Cycle includes closing node repeated; deduplicate for callback
                unique = list(dict.fromkeys(cycle))
                self.on_deadlock(unique)
                report.actions_taken.append(f"on_deadlock callback for cycle {unique}")
                report.deadlocks_broken += 1
            elif self.auto_recover:
                # Abort the youngest task (last created) to break the cycle
                unique = list(dict.fromkeys(cycle))
                candidates = [
                    tid for tid in unique if tid in tasks and not tasks[tid].is_terminal()
                ]
                if candidates:
                    youngest = max(
                        candidates,
                        key=lambda tid: tasks[tid].created_at or "",
                    )
                    tasks[youngest].status = TaskStatus.CANCELLED
                    tasks[youngest].error = "Aborted to break deadlock"
                    # Remove from blocked_by lists so remaining tasks unblock
                    for tid in candidates:
                        if youngest in tasks[tid].blocked_by:
                            tasks[tid].blocked_by.remove(youngest)
                    report.deadlocks_broken += 1
                    report.actions_taken.append(
                        f"auto-cancelled {youngest} to break deadlock cycle {unique}"
                    )

        return report

    def get_graph_status(self, tasks: dict[str, TaskHandle]) -> dict[str, Any]:
        """Return aggregate execution status for all tasks."""
        counts: dict[str, int] = {}
        for task_handle in tasks.values():
            status_key = task_handle.status.value
            counts[status_key] = counts.get(status_key, 0) + 1

        total = len(tasks)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        terminal = completed + failed + cancelled
        completion_pct = (terminal / total * 100) if total > 0 else 0.0

        return {
            "total": total,
            "counts": counts,
            "stuck_tasks": self.detect_stuck(),
            "estimated_completion_pct": round(completion_pct, 1),
        }

    def record_event(
        self,
        task_id: str,
        event: str,
        payload: dict | None = None,
    ) -> None:
        """Record an observation event."""
        self._events.append(
            {
                "task_id": task_id,
                "event": event,
                "payload": payload or {},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def get_timeline(self, task_id: str | None = None) -> list[dict]:
        """Get event timeline, optionally filtered by `task_id`."""
        if task_id is None:
            return list(self._events)
        return [event for event in self._events if event["task_id"] == task_id]

"""Task monitor: heartbeat, progress tracking, stuck detection."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from hi_agent.task_mgmt.handle import TaskHandle, TaskStatus


class TaskMonitor:
    """Observes task execution health."""

    def __init__(self, heartbeat_timeout_seconds: int = 300) -> None:
        self._heartbeats: dict[str, float] = {}   # task_id -> last_heartbeat_time
        self._progress: dict[str, dict] = {}       # task_id -> {pct, message, ...}
        self._events: list[dict] = []
        self._timeout = heartbeat_timeout_seconds

    def heartbeat(self, task_id: str, progress: dict | None = None) -> None:
        """Record heartbeat from a running task."""
        self._heartbeats[task_id] = time.monotonic()
        if progress is not None:
            self._progress[task_id] = progress
        self.record_event(task_id, "heartbeat", progress)

    def get_progress(self, task_id: str) -> dict | None:
        """Return progress info for *task_id*, or None."""
        return self._progress.get(task_id)

    def detect_stuck(self) -> list[str]:
        """Find tasks that have not sent a heartbeat within *timeout*.

        Returns list of stuck task_ids.
        """
        now = time.monotonic()
        stuck: list[str] = []
        for task_id, last_hb in self._heartbeats.items():
            if now - last_hb > self._timeout:
                stuck.append(task_id)
        return stuck

    def detect_deadlock(self, tasks: dict[str, TaskHandle]) -> list[list[str]]:
        """Detect circular dependency chains (deadlocks).

        Uses DFS colouring on the ``blocked_by`` graph among non-terminal
        tasks.  Returns a list of cycles (each cycle is a list of task_ids).
        """
        # Build adjacency: task_id -> list of task_ids it is blocked by
        adj: dict[str, list[str]] = {}
        active_ids: set[str] = set()
        for tid, th in tasks.items():
            if not th.is_terminal():
                active_ids.add(tid)
                adj[tid] = [b for b in th.blocked_by if b in tasks and not tasks[b].is_terminal()]

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {tid: WHITE for tid in active_ids}
        parent: dict[str, str | None] = {tid: None for tid in active_ids}
        cycles: list[list[str]] = []

        def _dfs(node: str) -> None:
            color[node] = GRAY
            for neighbor in adj.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # Found a cycle — reconstruct
                    cycle: list[str] = [neighbor]
                    cur = node
                    while cur != neighbor:
                        cycle.append(cur)
                        cur = parent.get(cur, neighbor)  # type: ignore[assignment]
                    cycle.append(neighbor)
                    cycle.reverse()
                    cycles.append(cycle)
                elif color[neighbor] == WHITE:
                    parent[neighbor] = node
                    _dfs(neighbor)
            color[node] = BLACK

        for tid in active_ids:
            if color.get(tid, WHITE) == WHITE:
                _dfs(tid)

        return cycles

    def get_graph_status(self, tasks: dict[str, TaskHandle]) -> dict[str, Any]:
        """Overall graph execution status.

        Returns counts per status, stuck tasks, estimated completion pct.
        """
        counts: dict[str, int] = {}
        for th in tasks.values():
            key = th.status.value
            counts[key] = counts.get(key, 0) + 1

        total = len(tasks)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        terminal = completed + failed + cancelled
        pct = (terminal / total * 100) if total > 0 else 0.0

        stuck = self.detect_stuck()

        return {
            "total": total,
            "counts": counts,
            "stuck_tasks": stuck,
            "estimated_completion_pct": round(pct, 1),
        }

    def record_event(self, task_id: str, event: str, payload: dict | None = None) -> None:
        """Record an observation event."""
        self._events.append({
            "task_id": task_id,
            "event": event,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_timeline(self, task_id: str | None = None) -> list[dict]:
        """Get event timeline, optionally filtered by *task_id*."""
        if task_id is None:
            return list(self._events)
        return [e for e in self._events if e["task_id"] == task_id]

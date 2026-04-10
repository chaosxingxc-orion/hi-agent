"""Task scheduler: superstep execution with yield/resume for dependencies.

Based on TrajectoryGraph. Each superstep:
1. Find ready tasks (deps completed, not blocked)
2. Execute in parallel (ThreadPoolExecutor)
3. Collect results
4. Handle yields (blocked on dependency -> schedule dependency)
5. Handle completions (notify dependents -> check if they become ready)
6. Repeat until all terminal

Yield/Resume:
  When a task discovers it needs a dependency that is not done:
  - yield_task(task_id, blocked_by=[dep_id])
  - Scheduler saves task session, marks YIELDED
  - Scheduler ensures dep_id is scheduled
  - When dep_id completes, scheduler resumes yielded task with results
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hi_agent.task_mgmt.handle import TaskHandle, TaskStatus
from hi_agent.task_mgmt.monitor import TaskMonitor
from hi_agent.task_mgmt.notification import (
    TaskCommunicator,
    TaskNotification,
)
from hi_agent.trajectory.graph import EdgeType, TrajectoryGraph


@dataclass
class ScheduleResult:
    """Result of a full scheduling run."""

    success: bool
    total_steps: int
    completed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    yielded_tasks: list[str] = field(default_factory=list)   # still waiting
    cancelled_tasks: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_duration_ms: int = 0


class TaskScheduler:
    """Superstep task scheduler with yield/resume support."""

    def __init__(
        self,
        max_workers: int = 4,
        communicator: TaskCommunicator | None = None,
        monitor: TaskMonitor | None = None,
    ) -> None:
        """Initialize TaskScheduler."""
        self._tasks: dict[str, TaskHandle] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._communicator = communicator or TaskCommunicator()
        self._monitor = monitor or TaskMonitor()
        self._lock = threading.Lock()
        self._step_count: int = 0
        self._default_execute_fn: Callable | None = None

    # ------------------------------------------------------------------
    # Graph loading
    # ------------------------------------------------------------------

    def load_graph(
        self,
        graph: TrajectoryGraph,
        execute_fn: Callable | None = None,
    ) -> None:
        """Create TaskHandles from TrajectoryGraph nodes.

        Resolve dependencies from graph edges (SEQUENCE, BRANCH).
        """
        self._default_execute_fn = execute_fn

        # Build node_id -> task_id mapping (identity for now)
        for node_id in graph.topological_sort():
            node = graph.get_node(node_id)
            if node is None:
                continue
            task = TaskHandle(
                task_id=node_id,
                node_id=node_id,
                status=TaskStatus.PENDING,
                max_retries=node.max_retries,
                created_at=datetime.now(UTC).isoformat(),
            )
            self._tasks[node_id] = task

        # Resolve dependencies from edges
        for edge in graph._edges:
            if edge.edge_type in (EdgeType.SEQUENCE, EdgeType.BRANCH):
                src = edge.source
                tgt = edge.target
                if tgt in self._tasks and src in self._tasks:
                    if src not in self._tasks[tgt].dependencies:
                        self._tasks[tgt].dependencies.append(src)
                    if tgt not in self._tasks[src].dependents:
                        self._tasks[src].dependents.append(tgt)

    # ------------------------------------------------------------------
    # Scheduling loop
    # ------------------------------------------------------------------

    def schedule(self, max_steps: int = 100) -> ScheduleResult:
        """Run superstep loop until all tasks terminal or *max_steps*.

        Each superstep:
        1. get_ready_tasks() -> tasks with all deps completed + not blocked
        2. dispatch_parallel(ready_tasks) -> execute via ThreadPool
        3. collect_results() -> gather futures
        4. handle_yields() -> for yielded tasks, schedule their blockers
        5. handle_completions() -> notify dependents, unblock waiting tasks
        6. check_terminal() -> all done?
        """
        start_ms = _now_ms()
        for _ in range(max_steps):
            self._step_count += 1
            ready = self.get_ready_tasks()

            if not ready and not self._has_running():
                break

            if not ready:
                # Nothing ready but something running — skip (shouldn't happen
                # in synchronous dispatch, but guard anyway).
                break

            # Dispatch ready tasks and wait for this superstep to complete
            futures: dict[Future, str] = {}
            for task in ready:
                fut = self._dispatch_task(task)
                futures[fut] = task.task_id

            # Collect results (blocks until all in this step are done)
            for fut in as_completed(futures):
                tid = futures[fut]
                try:
                    result = fut.result()
                    self._on_task_done(tid, result, None)
                except Exception as exc:
                    self._on_task_done(tid, None, str(exc))

            # After completions, check if any yielded tasks can be unblocked
            for tid in list(self._tasks):
                th = self._tasks[tid]
                if th.status == TaskStatus.COMPLETED:
                    resumed = self._check_unblock(tid)
                    for rtid in resumed:
                        self.resume_task(rtid)

            if self.all_terminal:
                break

        duration = _now_ms() - start_ms
        return self._build_result(duration)

    # ------------------------------------------------------------------
    # Yield / Resume
    # ------------------------------------------------------------------

    def yield_task(
        self,
        task_id: str,
        blocked_by: list[str],
        session_snapshot: dict | None = None,
        reason: str = "",
    ) -> None:
        """Yield a task: save session, mark YIELDED, ensure blockers are scheduled."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.status = TaskStatus.YIELDED
            task.session_snapshot = session_snapshot
            task.yield_reason = reason
            task.blocked_by = list(blocked_by)

        self._communicator.notify(TaskNotification(
            task_id=task_id, event="yielded",
            payload={"blocked_by": blocked_by, "reason": reason},
        ))

        # Ensure blockers are scheduled (set to PENDING if they are not yet)
        for bid in blocked_by:
            with self._lock:
                blocker = self._tasks.get(bid)
                if blocker and blocker.status == TaskStatus.PENDING:
                    pass  # will be picked up next superstep

    def resume_task(
        self,
        task_id: str,
        dependency_results: dict | None = None,
    ) -> None:
        """Resume a yielded task: restore session, inject dep results, mark READY."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.YIELDED:
                return
            task.status = TaskStatus.READY
            task.blocked_by = []
            if dependency_results and task.session_snapshot is not None:
                task.session_snapshot["dependency_results"] = dependency_results

        self._communicator.notify(TaskNotification(
            task_id=task_id, event="resumed",
            payload={"dependency_results": dependency_results or {}},
        ))

    def cancel_task(self, task_id: str, reason: str = "") -> None:
        """Cancel a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.is_terminal():
                return
            task.status = TaskStatus.CANCELLED
            task.error = reason
            task.completed_at = datetime.now(UTC).isoformat()

        self._communicator.notify(TaskNotification(
            task_id=task_id, event="cancelled",
            payload={"reason": reason},
        ))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_ready_tasks(self) -> list[TaskHandle]:
        """Tasks whose all dependencies are COMPLETED and status is PENDING/READY."""
        ready: list[TaskHandle] = []
        with self._lock:
            for task in self._tasks.values():
                if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
                    continue
                all_deps_done = all(
                    self._tasks[dep].status == TaskStatus.COMPLETED
                    for dep in task.dependencies
                    if dep in self._tasks
                )
                if all_deps_done:
                    ready.append(task)
        return ready

    def get_blocked_tasks(self) -> list[TaskHandle]:
        """Tasks in BLOCKED or YIELDED status."""
        return [t for t in self._tasks.values() if t.is_blocked()]

    @property
    def all_terminal(self) -> bool:
        """True when every task is in a terminal state."""
        return all(t.is_terminal() for t in self._tasks.values()) if self._tasks else True

    def get_status(self) -> dict[str, Any]:
        """Return current scheduler status summary."""
        return self._monitor.get_graph_status(self._tasks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch_task(self, task: TaskHandle) -> Future:
        """Execute task in thread pool. Returns the Future."""
        with self._lock:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(UTC).isoformat()

        self._communicator.notify(TaskNotification(
            task_id=task.task_id, event="started",
        ))
        self._monitor.heartbeat(task.task_id)

        fn = task._execute_fn or self._default_execute_fn
        if fn is not None:
            return self._executor.submit(fn, task)
        else:
            # Default: no-op execution
            return self._executor.submit(lambda t: None, task)

    def _on_task_done(
        self, task_id: str, result: Any, error: str | None,
    ) -> None:
        """Handle task completion: update status, notify dependents."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            now_iso = datetime.now(UTC).isoformat()
            if error is not None:
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING
                    task.error = None
                    return
                task.status = TaskStatus.FAILED
                task.error = error
                task.completed_at = now_iso
            else:
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = now_iso

        event = "completed" if error is None else "failed"
        self._communicator.notify(TaskNotification(
            task_id=task_id, event=event,
            result=result,
            payload={"error": error} if error else {},
        ))
        self._monitor.record_event(task_id, event)

    def _check_unblock(self, completed_task_id: str) -> list[str]:
        """Check which yielded tasks can be resumed after this task completed.

        Returns list of task_ids to resume.
        """
        to_resume: list[str] = []
        with self._lock:
            for task in self._tasks.values():
                if task.status != TaskStatus.YIELDED:
                    continue
                if completed_task_id in task.blocked_by:
                    # Remove from blocked_by
                    task.blocked_by = [
                        b for b in task.blocked_by if b != completed_task_id
                    ]
                    if not task.blocked_by:
                        to_resume.append(task.task_id)
        return to_resume

    def _has_running(self) -> bool:
        """Check if any task is currently RUNNING."""
        return any(t.status == TaskStatus.RUNNING for t in self._tasks.values())

    def _build_result(self, duration_ms: int) -> ScheduleResult:
        """Build the final ScheduleResult."""
        completed: list[str] = []
        failed: list[str] = []
        yielded: list[str] = []
        cancelled: list[str] = []
        total_tokens = 0

        for task in self._tasks.values():
            total_tokens += task.tokens_used
            if task.status == TaskStatus.COMPLETED:
                completed.append(task.task_id)
            elif task.status == TaskStatus.FAILED:
                failed.append(task.task_id)
            elif task.status == TaskStatus.YIELDED:
                yielded.append(task.task_id)
            elif task.status == TaskStatus.CANCELLED:
                cancelled.append(task.task_id)

        success = len(failed) == 0 and len(completed) > 0

        return ScheduleResult(
            success=success,
            total_steps=self._step_count,
            completed_tasks=completed,
            failed_tasks=failed,
            yielded_tasks=yielded,
            cancelled_tasks=cancelled,
            total_tokens=total_tokens,
            total_duration_ms=duration_ms,
        )


def _now_ms() -> int:
    """Current time in milliseconds (monotonic)."""
    return int(time.monotonic() * 1000)

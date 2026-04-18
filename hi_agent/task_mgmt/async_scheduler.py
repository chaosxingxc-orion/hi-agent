"""Async task scheduler using asyncio + Semaphore + O(1) ready detection.

Design:
  - `asyncio.Semaphore(max_concurrency)` limits concurrent handlers.
  - `pending_count: dict[str, int]` enables O(1) dependency checks.
  - `waiters: dict[str, list[str]]` maps each node to waiting nodes.
  - `ready_queue: asyncio.Queue[str]` feeds runnable node IDs to workers.
  - `add_node()` supports dynamic graph growth during execution.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hi_agent.trajectory.graph import NodeState, TrajectoryGraph, TrajNode


@dataclass
class ScheduleResult:
    """Represents one scheduler run outcome."""

    success: bool
    completed_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    error: str | None = None


class AsyncTaskScheduler:
    """Schedules and executes a TrajectoryGraph asynchronously.

    Usage::

        scheduler = AsyncTaskScheduler(kernel=facade, max_concurrency=8)
        result = await scheduler.run(graph, run_id="run-001", make_handler=make_handler)

    `make_handler` is an async callable `(node_id: str) -> AsyncActionHandler`.
    Handlers receive `(action, sandbox_grant)` and return any JSON-serialisable
    value.
    """

    def __init__(self, kernel: Any, max_concurrency: int = 8) -> None:
        """Initialize AsyncTaskScheduler."""
        self._kernel = kernel
        self._max_concurrency = max_concurrency
        # Populated fresh for each run() call.
        self._semaphore: asyncio.Semaphore | None = None
        self._graph: TrajectoryGraph | None = None
        self._run_id: str = ""
        self._make_handler: Callable | None = None
        self._pending_count: dict[str, int] = {}
        self._waiters: dict[str, list[str]] = {}
        self._ready_queue: asyncio.Queue[str] = asyncio.Queue()
        self._completed: list[str] = []
        self._failed: list[str] = []
        self._in_flight: int = 0
        self._done_event: asyncio.Event | None = None

    def add_node(
        self,
        node: TrajNode,
        depends_on: list[str] | None = None,
    ) -> None:
        """Dynamically add a node during execution.

        Safe to call from inside a running handler (asyncio single-thread).
        `depends_on` lists node IDs that must complete first.
        """
        depends_on = depends_on or []
        assert self._graph is not None, "add_node() called outside of run()"

        self._graph.add_node(node)
        for dep in depends_on:
            self._graph.add_sequence(dep, node.node_id)

        pending = sum(1 for dep in depends_on if dep not in self._completed)
        self._pending_count[node.node_id] = pending

        for dep in depends_on:
            if dep not in self._completed:
                self._waiters.setdefault(dep, []).append(node.node_id)

        if pending == 0:
            self._in_flight += 1
            self._ready_queue.put_nowait(node.node_id)

    async def run(
        self,
        graph: TrajectoryGraph,
        run_id: str,
        make_handler: Callable,
    ) -> ScheduleResult:
        """Execute all nodes, respecting dependencies and concurrency cap."""
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._graph = graph
        self._run_id = run_id
        self._make_handler = make_handler
        self._completed = []
        self._failed = []
        self._pending_count = {}
        self._waiters = {}
        self._ready_queue = asyncio.Queue()
        self._in_flight = 0
        self._done_event = asyncio.Event()

        for node_id, _node in graph._nodes.items():
            incoming = graph.get_incoming(node_id)
            deps = [edge.source for edge in incoming]
            self._pending_count[node_id] = len(deps)
            for dep in deps:
                self._waiters.setdefault(dep, []).append(node_id)

        for node_id, count in self._pending_count.items():
            if count == 0:
                self._in_flight += 1
                self._ready_queue.put_nowait(node_id)

        if self._in_flight == 0:
            self._done_event.set()
            return ScheduleResult(success=True)

        worker_tasks: set[asyncio.Task[None]] = set()

        async def _dispatch() -> None:
            while True:
                node_id = await self._ready_queue.get()
                worker_task = asyncio.create_task(self._execute_node(node_id))
                worker_tasks.add(worker_task)
                worker_task.add_done_callback(worker_tasks.discard)

        dispatch_task = asyncio.create_task(_dispatch())
        await self._done_event.wait()
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task

        if worker_tasks:
            await asyncio.gather(*worker_tasks, return_exceptions=True)

        return ScheduleResult(
            success=len(self._failed) == 0,
            completed_nodes=list(self._completed),
            failed_nodes=list(self._failed),
        )

    async def _execute_node(self, node_id: str) -> None:
        """Execute a single node under the concurrency semaphore."""
        from agent_kernel.kernel.contracts import Action

        assert self._graph is not None
        assert self._semaphore is not None
        assert self._done_event is not None

        node = self._graph.get_node(node_id)
        self._graph.update_node_state(node_id, NodeState.RUNNING)

        action = Action(
            action_id=node_id,
            run_id=self._run_id,
            action_type="execute_node",
            effect_class="read_only",
            input_json={"node_id": node_id, **(node.payload if node else {})},
        )
        handler = await self._make_handler(node_id)

        async with self._semaphore:
            try:
                result = await asyncio.wait_for(
                    self._kernel.execute_turn(
                        run_id=self._run_id,
                        action=action,
                        handler=handler,
                        idempotency_key=f"{self._run_id}:{node_id}",
                    ),
                    timeout=300.0,  # 5-minute per-node hard timeout
                )
                self._graph.update_node_state(
                    node_id,
                    NodeState.COMPLETED,
                    result=result,
                )
                self._completed.append(node_id)
                self._unblock_waiters(node_id)
            except Exception as exc:
                self._graph.update_node_state(
                    node_id,
                    NodeState.FAILED,
                    failure_reason=str(exc),
                )
                self._failed.append(node_id)
            finally:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._done_event.set()

    def _unblock_waiters(self, completed_node_id: str) -> None:
        """Decrement pending_count for waiters and enqueue newly-ready nodes."""
        for waiter_id in self._waiters.get(completed_node_id, []):
            self._pending_count[waiter_id] -= 1
            if self._pending_count[waiter_id] == 0:
                self._in_flight += 1
                self._ready_queue.put_nowait(waiter_id)

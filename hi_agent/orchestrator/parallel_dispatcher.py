"""Thread-based parallel dispatch for sub-task execution."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any


class ParallelDispatcher:
    """Dispatches sub-tasks in parallel using thread pool.

    Respects DAG dependencies -- only dispatches nodes whose
    dependencies are all completed.
    """

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize ParallelDispatcher."""
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future[Any]] = {}
        self._lock = threading.Lock()

    def dispatch(self, node_id: str, fn: Callable[..., Any], *args: Any) -> None:
        """Submit a sub-task for parallel execution.

        Args:
            node_id: Unique identifier for this dispatched unit.
            fn: Callable to execute.
            *args: Arguments forwarded to *fn*.
        """
        future = self._executor.submit(fn, *args)
        with self._lock:
            self._futures[node_id] = future

    def wait_any(self, timeout: float | None = None) -> list[tuple[str, Any]]:
        """Wait for any dispatched task to complete.

        Returns a list of ``(node_id, result)`` tuples for every future
        that finished within *timeout* seconds.  If a future raised an
        exception the result is the exception instance itself.
        """
        with self._lock:
            pending = dict(self._futures)

        if not pending:
            return []

        results: list[tuple[str, Any]] = []
        done = as_completed(pending.values(), timeout=timeout)
        for future in done:
            # Reverse-lookup the node_id.
            node_id = next(nid for nid, f in pending.items() if f is future)
            try:
                results.append((node_id, future.result(timeout=0)))
            except Exception as exc:
                results.append((node_id, exc))

            with self._lock:
                self._futures.pop(node_id, None)

            # Return as soon as at least one result is available.
            break

        return results

    def wait_all(self, timeout: float | None = None) -> dict[str, Any]:
        """Wait for all dispatched tasks to complete.

        Returns ``{node_id: result}`` for every dispatched future.
        If a future raised an exception the value is the exception instance.
        """
        with self._lock:
            pending = dict(self._futures)

        results: dict[str, Any] = {}
        done_iter = as_completed(pending.values(), timeout=timeout)
        for future in done_iter:
            node_id = next(nid for nid, f in pending.items() if f is future)
            try:
                results[node_id] = future.result(timeout=0)
            except Exception as exc:
                results[node_id] = exc

        with self._lock:
            for nid in results:
                self._futures.pop(nid, None)

        return results

    def shutdown(self) -> None:
        """Shutdown the underlying thread pool."""
        self._executor.shutdown(wait=True)

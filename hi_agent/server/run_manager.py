"""Run lifecycle manager for the API server.

Manages creation, execution, querying, and cancellation of runs.
Uses threading for concurrent run execution (stdlib only).
"""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ManagedRun:
    """A run managed by the server."""

    run_id: str
    task_contract: dict[str, Any]
    state: str = "created"
    result: Any = None
    error: str | None = None
    thread: threading.Thread | None = field(default=None, repr=False)
    created_at: str = ""
    updated_at: str = ""


class RunManager:
    """Thread-safe run lifecycle manager with bounded queue and backoff.

    When all concurrency slots are occupied, incoming runs are placed in a
    bounded queue instead of being rejected immediately.  A background worker
    thread drains the queue, acquires the semaphore, and dispatches each run.
    Only when the queue itself is full does the manager reject with
    ``queue_full``.
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        queue_size: int = 16,
        queue_timeout_s: float = 30.0,
    ) -> None:
        """Initialize the run manager.

        Args:
            max_concurrent: Maximum number of concurrently executing runs.
            queue_size: Maximum number of runs waiting in the queue.
            queue_timeout_s: Seconds a queued run waits for a concurrency slot
                before being marked as timed-out.
        """
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._queue: queue.Queue[
            tuple[ManagedRun, Callable[[ManagedRun], Any]]
        ] = queue.Queue(maxsize=queue_size)
        self._queue_size = queue_size
        self._queue_timeout_s = queue_timeout_s
        self._active_count = 0  # guarded by _lock
        self._shutdown = False

        # Background worker that drains the queue.
        self._worker = threading.Thread(target=self._queue_worker, daemon=True)
        self._worker.start()

    def create_run(self, task_contract_dict: dict[str, Any]) -> str:
        """Create a new run from task contract dict.

        Args:
            task_contract_dict: Serialized TaskContract fields.

        Returns:
            The new run_id.
        """
        run_id = task_contract_dict.get("task_id") or uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        run = ManagedRun(
            run_id=run_id,
            task_contract=task_contract_dict,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._runs[run_id] = run
        return run_id

    # -- internal helpers -----------------------------------------------------

    def _queue_worker(self) -> None:
        """Background worker: drain queue, acquire semaphore, dispatch."""
        while not self._shutdown:
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            run, executor_fn = item
            # Wait for a concurrency slot (with timeout).
            acquired = self._semaphore.acquire(timeout=self._queue_timeout_s)
            if not acquired:
                with self._lock:
                    run.state = "failed"
                    run.error = "queue_timeout"
                    run.updated_at = datetime.now(UTC).isoformat()
                self._queue.task_done()
                continue
            # Dispatch in a new thread so the worker can process the next item.
            thread = threading.Thread(
                target=self._execute_run, args=(run, executor_fn), daemon=True
            )
            thread.start()
            with self._lock:
                run.thread = thread
            self._queue.task_done()

    def _execute_run(
        self, run: ManagedRun, executor_fn: Callable[[ManagedRun], Any]
    ) -> None:
        """Execute a single run under the semaphore (already acquired)."""
        with self._lock:
            self._active_count += 1
            run.state = "running"
            run.updated_at = datetime.now(UTC).isoformat()
        try:
            result = executor_fn(run)
            with self._lock:
                run.state = "completed"
                run.result = result
                run.updated_at = datetime.now(UTC).isoformat()
        except Exception as exc:
            with self._lock:
                run.state = "failed"
                run.error = str(exc)
                run.updated_at = datetime.now(UTC).isoformat()
        finally:
            with self._lock:
                self._active_count -= 1
            self._semaphore.release()

    # -- public API ---------------------------------------------------------

    def start_run(self, run_id: str, executor_fn: Callable[[ManagedRun], Any]) -> None:
        """Start run execution in a background thread.

        If all concurrency slots are occupied the run is placed in a bounded
        queue.  Only when the queue is also full is the run rejected with
        ``queue_full``.

        Args:
            run_id: Identifier of a previously created run.
            executor_fn: Callable that receives the ManagedRun and executes it.
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            if run.state != "created":
                return

        # Try to enqueue (non-blocking).
        try:
            self._queue.put_nowait((run, executor_fn))
        except queue.Full:
            with self._lock:
                run.state = "failed"
                run.error = "queue_full"
                run.updated_at = datetime.now(UTC).isoformat()

    @property
    def pending_count(self) -> int:
        """Return the number of runs currently waiting in the queue."""
        return self._queue.qsize()

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot of manager capacity and utilisation.

        Returns:
            Dictionary with ``active_runs``, ``queued_runs``,
            ``total_capacity``, and ``queue_utilization`` (0.0-1.0).
        """
        with self._lock:
            active = self._active_count
        queued = self._queue.qsize()
        return {
            "active_runs": active,
            "queued_runs": queued,
            "total_capacity": self._max_concurrent,
            "queue_utilization": queued / self._queue_size if self._queue_size else 0.0,
        }

    def get_run(self, run_id: str) -> ManagedRun | None:
        """Retrieve a run by id.

        Args:
            run_id: Identifier of the run.

        Returns:
            The ManagedRun or None if not found.
        """
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[ManagedRun]:
        """List all managed runs.

        Returns:
            A list of all ManagedRun instances.
        """
        with self._lock:
            return list(self._runs.values())

    def cancel_run(self, run_id: str) -> bool:
        """Request cancellation of a run.

        Sets the run state to ``cancelled`` if it is still in ``created``
        or ``running`` state. Note: this does not forcibly terminate the
        thread but marks the run so callers can observe the cancellation.

        Args:
            run_id: Identifier of the run.

        Returns:
            True if the state was changed to cancelled, False otherwise.
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return False
            if run.state in ("created", "running"):
                run.state = "cancelled"
                run.updated_at = datetime.now(UTC).isoformat()
                return True
            return False

    def to_dict(self, run: ManagedRun) -> dict[str, Any]:
        """Serialize run to JSON-safe dict.

        Args:
            run: The managed run to serialize.

        Returns:
            A dictionary suitable for JSON serialization.
        """
        return {
            "run_id": run.run_id,
            "task_contract": run.task_contract,
            "state": run.state,
            "result": run.result,
            "error": run.error,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

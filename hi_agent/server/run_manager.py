"""Run lifecycle manager for the API server.

Manages creation, execution, querying, and cancellation of runs.
Uses threading for concurrent run execution (stdlib only).
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hi_agent.contracts.run import RunState
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload
from hi_agent.server.run_store import RunRecord, SQLiteRunStore

# Valid terminal/operational states that result_status may be mapped to.
_VALID_RESULT_STATES: frozenset[str] = frozenset(s.value for s in RunState)


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
        idempotency_store: IdempotencyStore | None = None,
        run_store: SQLiteRunStore | None = None,
    ) -> None:
        """Initialize the run manager.

        Args:
            max_concurrent: Maximum number of concurrently executing runs.
            queue_size: Maximum number of runs waiting in the queue.
            queue_timeout_s: Seconds a queued run waits for a concurrency slot
                before being marked as timed-out.
            idempotency_store: Optional SQLite-backed idempotency store.  When
                provided, ``create_run`` honours ``idempotency_key`` in the
                request payload to deduplicate submissions.
            run_store: Optional SQLite-backed run store.  When provided, each
                new run is persisted so state survives process restarts.
        """
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._idempotency_store = idempotency_store
        self._run_store = run_store
        # PriorityQueue: items are (priority, sequence, run, executor_fn).
        # Lower priority integer = higher urgency (1 executes before 5).
        # sequence is a monotonic counter that breaks priority ties (FIFO within tier).
        self._queue: queue.PriorityQueue[
            tuple[int, int, ManagedRun, Callable[[ManagedRun], Any]]
        ] = queue.PriorityQueue(maxsize=queue_size)
        self._queue_seq: int = 0  # monotonic counter for tie-breaking
        self._queue_size = queue_size
        self._queue_timeout_s = queue_timeout_s
        self._active_count = 0  # guarded by _lock
        self._shutdown = False

        # Background worker that drains the queue.
        self._worker = threading.Thread(target=self._queue_worker, daemon=True)
        self._worker.start()

    def create_run(self, task_contract_dict: dict[str, Any]) -> str:
        """Create a new run from task contract dict.

        When an ``idempotency_store`` is configured and the request carries an
        ``idempotency_key`` field, deduplication is enforced:

        - ``"replayed"``  → returns the existing run_id (no new run created).
        - ``"conflict"``  → raises ``ValueError("idempotency_conflict")`` so the
          caller can return HTTP 409.
        - ``"created"``   → falls through to normal run creation.

        When a ``run_store`` is configured, the new run is persisted to SQLite
        before being placed in the in-memory registry.

        Args:
            task_contract_dict: Serialized TaskContract fields.

        Returns:
            The new (or previously replayed) run_id.

        Raises:
            ValueError: With message ``"idempotency_conflict"`` when the same
                idempotency key is submitted with a different request payload.
        """
        idempotency_key: str | None = task_contract_dict.get("idempotency_key")
        tenant_id: str = task_contract_dict.get("tenant_id", "default")

        # --- idempotency check (only when store + key are present) ----------
        if self._idempotency_store is not None and idempotency_key:
            # Build hash from payload excluding the idempotency_key itself so
            # that the canonical hash represents the actual request content.
            payload_for_hash = {
                k: v for k, v in task_contract_dict.items() if k != "idempotency_key"
            }
            request_hash = _hash_payload(payload_for_hash)
            # Allocate a tentative run_id; only used on "created" path.
            candidate_run_id = task_contract_dict.get("task_id") or uuid.uuid4().hex[:12]

            outcome, record = self._idempotency_store.reserve_or_replay(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                run_id=candidate_run_id,
            )

            if outcome == "conflict":
                raise ValueError("idempotency_conflict")

            if outcome == "replayed":
                return record.run_id

            # outcome == "created" — continue with candidate_run_id below.
            run_id = candidate_run_id
        else:
            run_id = task_contract_dict.get("task_id") or uuid.uuid4().hex[:12]

        # --- normal run creation -------------------------------------------
        now = datetime.now(UTC).isoformat()
        run = ManagedRun(
            run_id=run_id,
            task_contract=task_contract_dict,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._runs[run_id] = run

        # --- persist to run_store if available ------------------------------
        if self._run_store is not None:
            import time as _time
            now_ts = _time.time()
            self._run_store.upsert(RunRecord(
                run_id=run_id,
                tenant_id=tenant_id,
                task_contract_json=json.dumps(task_contract_dict),
                status="queued",
                priority=int(task_contract_dict.get("priority", 5)),
                attempt_count=0,
                cancellation_flag=False,
                result_summary="",
                error_summary="",
                created_at=now_ts,
                updated_at=now_ts,
            ))

        return run_id

    # -- internal helpers -----------------------------------------------------

    def _queue_worker(self) -> None:
        """Background worker: drain queue, acquire semaphore, dispatch."""
        while not self._shutdown:
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            _priority, _seq, run, executor_fn = item
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
                # Derive run state from the result's own status if available.
                # RunResult(status="failed") must NOT be surfaced as state="completed".
                result_status = getattr(result, "status", None)
                if result_status is not None and result_status != "completed":
                    # Guard: only accept known RunState values to prevent inconsistent state.
                    if result_status in _VALID_RESULT_STATES:
                        run.state = result_status  # e.g. "failed"
                    else:
                        # Unknown status string — treat as failure rather than silently
                        # accepting an invalid state that would confuse downstream consumers.
                        run.state = RunState.FAILED
                    run.error = getattr(result, "error", None) or result_status
                else:
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

        # Try to enqueue (non-blocking). Priority from task_contract (1=highest).
        priority = int(run.task_contract.get("priority", 5))
        with self._lock:
            seq = self._queue_seq
            self._queue_seq += 1
        try:
            self._queue.put_nowait((priority, seq, run, executor_fn))
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
        # Serialize result: use to_dict() if RunResult, else stringify for backward compat.
        result_payload: Any
        try:
            result_payload = run.result.to_dict()
        except AttributeError:
            result_payload = run.result
        return {
            "run_id": run.run_id,
            "task_contract": run.task_contract,
            "state": run.state,
            "result": result_payload,
            "error": run.error,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

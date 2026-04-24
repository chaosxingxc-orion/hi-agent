"""Run lifecycle manager for the API server.

Manages creation, execution, querying, and cancellation of runs.
Uses threading for concurrent run execution (stdlib only).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hi_agent.contracts.run import RunState
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload
from hi_agent.server.run_queue import RunQueue
from hi_agent.server.run_store import RunRecord, SQLiteRunStore
from hi_agent.server.tenant_context import TenantContext

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
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    current_stage: str | None = None
    stage_updated_at: str | None = None


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
        run_queue: RunQueue | None = None,
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
            run_queue: Optional lease-based durable run queue.  When provided,
                ``create_run`` enqueues the run and the worker loop uses
                ``claim_next``/``complete``/``fail`` instead of the in-memory
                PriorityQueue.  When ``None``, the original in-memory queue
                path is used unchanged.
        """
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._idempotency_store = idempotency_store
        self._run_store = run_store
        self._run_queue = run_queue
        # Maps run_id -> executor_fn when run_queue is used; populated by start_run.
        self._pending_executors: dict[str, Callable[[ManagedRun], Any]] = {}
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
        self._worker: threading.Thread | None = None

        # Subscribe to EventBus for stage transition events (sync observer path).
        try:
            from hi_agent.server.event_bus import event_bus as _event_bus

            _event_bus.add_sync_observer(self._on_stage_event)
        except Exception:
            pass

    def _on_stage_event(self, event: object) -> None:
        """Update current_stage on any stage-entry event published to EventBus.

        P1-5: accept multiple event shapes so current_stage is updated reliably
        regardless of which code path emitted the transition:

        - ``stage_start`` with payload ``{"stage_name": ...}`` (StageOrchestrator)
        - ``StageStateChanged`` with payload ``{"stage_id": ..., "to_state": "active"}``
          (runner_stage direct emission)
        - Any future stage-entry event carrying ``stage_name`` or ``stage_id``.

        Previously only the first shape was honoured, leaving current_stage
        stuck at ``None`` whenever the run took a path that skipped the
        StageOrchestrator wrapper.
        """
        event_type = getattr(event, "event_type", None)
        if event_type not in ("stage_start", "StageStateChanged"):
            return
        payload = getattr(event, "payload_json", None) or {}
        if isinstance(payload, str):
            try:
                import json as _json

                payload = _json.loads(payload)
            except Exception:
                return
        if not isinstance(payload, dict):
            return
        # StageStateChanged is only a stage-entry signal when transitioning to active.
        if event_type == "StageStateChanged" and payload.get("to_state") != "active":
            return
        stage_name = payload.get("stage_name") or payload.get("stage_id")
        run_id = getattr(event, "run_id", None)
        if not stage_name or not run_id:
            return
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.current_stage = stage_name
                run.stage_updated_at = datetime.now(UTC).isoformat()

    def _owns(self, run: ManagedRun, ctx: TenantContext) -> bool:
        """Return True if the run belongs to the given workspace context.

        session_id is only enforced when the caller provides one (non-empty).
        An empty ctx.session_id means "all sessions for this user".
        """
        if run.tenant_id != ctx.tenant_id or run.user_id != ctx.user_id:
            return False
        if ctx.session_id:  # if caller provided a session, require exact match
            return run.session_id == ctx.session_id
        return True  # no session filter: matches all sessions for this user

    def _task_id_exists_unlocked(self, task_id: str, workspace: TenantContext | None) -> bool:
        """Return True if a run with the given task_id exists in the workspace.

        Must be called while holding ``self._lock``.
        """
        for run in self._runs.values():
            if run.task_contract.get("task_id") == task_id and (
                workspace is None or self._owns(run, workspace)
            ):
                return True
        return False

    def create_run(
        self,
        task_contract_dict: dict[str, Any],
        workspace: TenantContext | None = None,
    ) -> str:
        """Create a new run from task contract dict.

        When an ``idempotency_store`` is configured and the request carries an
        ``idempotency_key`` field, deduplication is enforced:

        - ``"replayed"``  → returns the existing run_id (no new run created).
        - ``"conflict"``  → raises ``ValueError("idempotency_conflict")`` so the
          caller can return HTTP 409.
        - ``"created"``   → falls through to normal run creation.

        When a ``run_store`` is configured, the new run is persisted to SQLite
        before being placed in the in-memory registry.

        When ``workspace`` is provided, the run is bound to that workspace and a
        duplicate ``task_id`` within the same workspace raises ``ValueError``.

        Args:
            task_contract_dict: Serialized TaskContract fields.
            workspace: Optional tenant/user/session context to bind to the run.

        Returns:
            The new (or previously replayed) run_id.

        Raises:
            ValueError: With message ``"idempotency_conflict"`` when the same
                idempotency key is submitted with a different request payload.
            ValueError: When a run with the same ``task_id`` already exists in
                the workspace.
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
            # Allocate a tentative run_id as UUID4; only used on "created" path.
            candidate_run_id = str(uuid.uuid4())

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
            run_id = str(uuid.uuid4())

        # --- normal run creation -------------------------------------------
        now = datetime.now(UTC).isoformat()
        run = ManagedRun(
            run_id=run_id,
            task_contract=task_contract_dict,
            created_at=now,
            updated_at=now,
            tenant_id=workspace.tenant_id if workspace else "",
            user_id=workspace.user_id if workspace else "",
            session_id=workspace.session_id if workspace else "",
        )
        # --- duplicate task_id check and insertion under the same lock ------
        client_task_id = task_contract_dict.get("task_id", "")
        with self._lock:
            if client_task_id and self._task_id_exists_unlocked(client_task_id, workspace):
                raise ValueError(f"run with task_id '{client_task_id}' already exists in workspace")
            self._runs[run_id] = run

        # --- persist to run_store if available ------------------------------
        if self._run_store is not None:
            import time as _time

            now_ts = _time.time()
            self._run_store.upsert(
                RunRecord(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    user_id=workspace.user_id if workspace else "__legacy__",
                    session_id=workspace.session_id if workspace else "__legacy__",
                    task_contract_json=json.dumps(task_contract_dict),
                    status="queued",
                    priority=int(task_contract_dict.get("priority", 5)),
                    attempt_count=0,
                    cancellation_flag=False,
                    result_summary="",
                    error_summary="",
                    created_at=now_ts,
                    updated_at=now_ts,
                )
            )

        # --- enqueue to durable run_queue if available ----------------------
        if self._run_queue is not None:
            self._run_queue.enqueue(
                run_id=run_id,
                priority=int(task_contract_dict.get("priority", 5)),
                payload_json=json.dumps(task_contract_dict),
            )

        return run_id

    # -- internal helpers -----------------------------------------------------

    def _queue_worker(self) -> None:
        """Background worker: drain queue, acquire semaphore, dispatch.

        When a ``RunQueue`` is wired in, this method claims the next run
        from the durable queue and calls ``complete``/``fail`` after
        execution.  The in-memory PriorityQueue path remains unchanged when
        ``run_queue`` is ``None``.
        """
        idle_cycles = 0
        max_idle_cycles = 20
        while not self._shutdown:
            if self._run_queue is not None:
                self._run_queue.release_expired_leases()
                claim = self._run_queue.claim_next(worker_id="run_manager")
                if claim is None:
                    import time as _time

                    idle_cycles += 1
                    with self._lock:
                        can_stop = self._active_count == 0 and not self._pending_executors
                    if idle_cycles >= max_idle_cycles and can_stop:
                        break
                    _time.sleep(0.1)
                    continue
                idle_cycles = 0
                run_id = claim["run_id"]
                with self._lock:
                    run = self._runs.get(run_id)
                    executor_fn = self._pending_executors.pop(run_id, None)
                if run is None or executor_fn is None:
                    # Run was created but executor not yet registered; release.
                    self._run_queue.fail(run_id, "run_manager", "executor_not_found")
                    continue
                acquired = self._semaphore.acquire(timeout=self._queue_timeout_s)
                if not acquired:
                    self._run_queue.fail(run_id, "run_manager", "queue_timeout")
                    with self._lock:
                        run.state = "failed"
                        run.error = "queue_timeout"
                        run.updated_at = datetime.now(UTC).isoformat()
                    continue
                thread = threading.Thread(
                    target=self._execute_run_durable,
                    args=(run, executor_fn, run_id),
                    daemon=True,
                )
                thread.start()
                with self._lock:
                    run.thread = thread
            else:
                try:
                    item = self._queue.get(timeout=0.25)
                except queue.Empty:
                    idle_cycles += 1
                    with self._lock:
                        can_stop = self._active_count == 0 and self._queue.empty()
                    if idle_cycles >= max_idle_cycles and can_stop:
                        break
                    continue
                idle_cycles = 0
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
        # Mark worker stopped so a future start_run can recreate it.
        with self._lock:
            self._worker = None

    def _ensure_worker_started(self) -> None:
        """Start the background worker on-demand if it is not running."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._shutdown = False
            self._worker = threading.Thread(target=self._queue_worker, daemon=True)
            self._worker.start()

    def _execute_run(self, run: ManagedRun, executor_fn: Callable[[ManagedRun], Any]) -> None:
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

    def _execute_run_durable(
        self,
        run: ManagedRun,
        executor_fn: Callable[[ManagedRun], Any],
        run_id: str,
    ) -> None:
        """Execute a run claimed from the durable RunQueue.

        Calls ``run_queue.complete`` on success or ``run_queue.fail`` on
        exception.  Semaphore was already acquired by the caller.
        """
        with self._lock:
            self._active_count += 1
            run.state = "running"
            run.updated_at = datetime.now(UTC).isoformat()
        try:
            result = executor_fn(run)
            with self._lock:
                result_status = getattr(result, "status", None)
                if result_status is not None and result_status != "completed":
                    if result_status in _VALID_RESULT_STATES:
                        run.state = result_status
                    else:
                        run.state = RunState.FAILED
                    run.error = getattr(result, "error", None) or result_status
                else:
                    run.state = "completed"
                run.result = result
                run.updated_at = datetime.now(UTC).isoformat()
            if self._run_queue is not None:
                if run.state == "completed":
                    self._run_queue.complete(run_id, "run_manager")
                else:
                    self._run_queue.fail(run_id, "run_manager", run.error or "")
        except Exception as exc:
            with self._lock:
                run.state = "failed"
                run.error = str(exc)
                run.updated_at = datetime.now(UTC).isoformat()
            if self._run_queue is not None:
                self._run_queue.fail(run_id, "run_manager", str(exc))
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
        self._ensure_worker_started()

        if self._run_queue is not None:
            # Durable queue path: store executor so the worker can look it up.
            with self._lock:
                self._pending_executors[run_id] = executor_fn
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

    def get_run(self, run_id: str, workspace: TenantContext | None = None) -> ManagedRun | None:
        """Retrieve a run by id.

        When ``workspace`` is provided, returns None if the run does not belong
        to that workspace.

        Args:
            run_id: Identifier of the run.
            workspace: Optional tenant/user/session filter.

        Returns:
            The ManagedRun or None if not found or not owned by workspace.
        """
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            return None
        if workspace and not self._owns(run, workspace):
            return None
        return run

    def list_runs(self, workspace: TenantContext | None = None) -> list[ManagedRun]:
        """List managed runs, optionally filtered by workspace.

        Args:
            workspace: When provided, only runs belonging to this workspace are
                returned.

        Returns:
            A list of ManagedRun instances.
        """
        with self._lock:
            runs = list(self._runs.values())
        if workspace:
            runs = [r for r in runs if self._owns(r, workspace)]
        return runs

    def cancel_run(self, run_id: str, workspace: TenantContext | None = None) -> bool:
        """Request cancellation of a run.

        Sets the run state to ``cancelled`` if it is still in ``created``
        or ``running`` state. When ``workspace`` is provided, returns False
        if the run does not belong to that workspace.

        Args:
            run_id: Identifier of the run.
            workspace: Optional tenant/user/session ownership check.

        Returns:
            True if the state was changed to cancelled, False otherwise.
        """
        run = self.get_run(run_id, workspace)
        if run is None:
            return False
        with self._lock:
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
        # Surface llm_fallback_count and finished_at from RunResult when available.
        _result = run.result
        _llm_fallback_count: int = 0
        _finished_at: str | None = None
        if _result is not None and hasattr(_result, "llm_fallback_count"):
            _llm_fallback_count = int(_result.llm_fallback_count or 0)
        if _result is not None and hasattr(_result, "finished_at"):
            _finished_at = _result.finished_at
        # Include top-level fallback_events recorded at the server boundary
        # (e.g. route/missing_profile_id events from routes_runs.py).
        # These are keyed on the server-boundary run_id, which differs from the
        # executor's internal run_id used by RunResult.fallback_events.
        from hi_agent.observability.fallback import get_fallback_events as _gfe

        _top_fallback_events: list[dict] = list(_gfe(run.run_id))
        return {
            "run_id": run.run_id,
            "task_contract": run.task_contract,
            "state": run.state,
            "result": result_payload,
            "error": run.error,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "current_stage": run.current_stage,
            "stage_updated_at": run.stage_updated_at,
            "llm_fallback_count": _llm_fallback_count,
            "finished_at": _finished_at,
            "fallback_events": _top_fallback_events,
        }

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop the background worker thread and prevent new queue loops.

        This is primarily used by server/test teardown to avoid leaking daemon
        worker threads across many short-lived RunManager instances.
        """
        deadline = time.monotonic() + max(timeout, 0.1)
        with self._lock:
            self._shutdown = True
            worker = self._worker
            # Prevent durable queue workers from picking up executor callbacks
            # after shutdown has started.
            self._pending_executors.clear()

        if worker is not None and worker.is_alive():
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(timeout=remaining)

        # Best-effort: wait for in-flight run threads to finish so app teardown
        # does not close shared resources (stores/transports) while they're in use.
        while time.monotonic() < deadline:
            with self._lock:
                active_threads = [
                    run.thread
                    for run in self._runs.values()
                    if run.thread is not None and run.thread.is_alive()
                ]
            if not active_threads:
                break

            remaining = max(0.0, deadline - time.monotonic())
            join_slice = min(0.1, remaining)
            if join_slice <= 0:
                break
            for thread in active_threads:
                thread.join(timeout=join_slice)

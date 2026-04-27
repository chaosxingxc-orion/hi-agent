"""Run lifecycle manager for the API server.

Manages creation, execution, querying, and cancellation of runs.
Uses threading for concurrent run execution (stdlib only).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import threading
import time
import uuid
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hi_agent.config.posture import Posture
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.contracts.run import RunState
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload
from hi_agent.server.run_queue import RunQueue
from hi_agent.server.run_store import RunRecord, SQLiteRunStore
from hi_agent.server.tenant_context import TenantContext

# Valid terminal/operational states that result_status may be mapped to.
_VALID_RESULT_STATES: frozenset[str] = frozenset(s.value for s in RunState)


class QueueSaturatedError(Exception):
    """Raised when the in-memory run queue is full and cannot accept new runs."""

    def __init__(self, queue_depth: int, max_depth: int) -> None:
        self.queue_depth = queue_depth
        self.max_depth = max_depth
        super().__init__(f"Queue saturated: {queue_depth}/{max_depth}")


def _run_state_to_terminal(state: str) -> str:
    """Map a ManagedRun.state to an idempotency terminal code (RO-7).

    Returns one of: "succeeded", "failed", "cancelled", "timed_out".
    """
    if state in ("completed", "succeeded"):
        return "succeeded"
    if state == "cancelled":
        return "cancelled"
    if state in ("timed_out", "queue_timeout"):
        return "timed_out"
    return "failed"


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
    # RO-8: finished_at is set by _execute_run/_execute_run_durable in the
    # finally block so that every terminal state (success, failure, cancel)
    # populates it — not only runs that produce a RunResult with .finished_at.
    finished_at: str | None = None
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    current_stage: str | None = None
    stage_updated_at: str | None = None
    idempotency_key: str | None = None
    outcome: str = "created"  # "created" | "replayed" | "conflict"
    response_snapshot: str = ""  # non-empty when replayed and original run is complete
    # Liveness fields
    started_at: str | None = None
    last_heartbeat_at: str | None = None
    current_action_id: str | None = None


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
        event_store: object | None = None,
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
            event_store: Optional SQLiteEventStore.  When provided,
                ``to_dict`` reads the most recent event offset and timestamp
                for liveness reporting.
        """
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._idempotency_store = idempotency_store
        self._run_store = run_store
        self._run_queue = run_queue
        self._event_store: SQLiteEventStore | None = event_store  # type: ignore[assignment]
        # Per-run sequence counters; seeded from storage on first use (restart-safe).
        self._event_seqs: dict[str, int] = {}
        self._event_seq_lock = threading.Lock()
        # Maps run_id -> executor_fn when run_queue is used; populated by start_run.
        self._pending_executors: dict[str, Callable[[ManagedRun], Any]] = {}
        # Maps run_id -> CancellationToken (or any object with .cancel()) for in-process signal.
        self._active_executor_tokens: dict[str, Any] = {}
        # Tracks run_ids that are currently executing (between start and finally block).
        self._active_run_ids: set[str] = set()
        # PriorityQueue: items are (priority, sequence, run, executor_fn).
        # Lower priority integer = higher urgency (1 executes before 5).
        # sequence is a monotonic counter that breaks priority ties (FIFO within tier).
        self._queue: queue.PriorityQueue[
            tuple[int, int, ManagedRun, Callable[[ManagedRun], Any]]
        ] = queue.PriorityQueue(maxsize=queue_size)
        # RUNTIME-ONLY: in-memory queue resets on restart; tie-breaking only.
        self._queue_seq: int = 0
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

    def set_event_store(self, store: SQLiteEventStore) -> None:
        """Inject the durable event store for run-progress event publishing.

        Args:
            store: SQLiteEventStore instance to receive run lifecycle events.
        """
        self._event_store = store

    def _publish_run_event(
        self,
        run_id: str,
        event_type: str,
        payload_dict: dict[str, Any],
        run: ManagedRun,
    ) -> None:
        """Append a structured lifecycle event to the event store if wired.

        Silently no-ops when ``self._event_store`` is None.  Never propagates
        exceptions — event publishing must not interrupt run execution.

        Args:
            run_id: Run identifier.
            event_type: One of run_queued / run_started / run_completed /
                run_failed / run_cancelled.
            payload_dict: Arbitrary JSON-serialisable payload dict.
            run: ManagedRun from which tenant/user/session spine is read.
        """
        if self._event_store is None:
            return
        with self._event_seq_lock:
            if run_id not in self._event_seqs and self._event_store is not None:
                try:
                    seed = self._event_store.max_sequence(run_id) + 1
                except Exception:
                    seed = 0
                self._event_seqs[run_id] = seed
            seq = self._event_seqs.get(run_id, 0)
            self._event_seqs[run_id] = seq + 1
        event = StoredEvent(
            event_id=str(uuid.uuid4()),
            run_id=run_id,
            sequence=seq,
            event_type=event_type,
            payload_json=json.dumps(payload_dict),
            tenant_id=run.tenant_id,
            user_id=run.user_id or "__legacy__",
            session_id=run.session_id or "__legacy__",
            created_at=datetime.now(UTC).timestamp(),
        )
        try:
            self._event_store.append(event)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "_publish_run_event: failed to append %s for run_id=%s: %s",
                event_type,
                run_id,
                exc,
            )

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
    ) -> ManagedRun:
        """Create a new run from task contract dict.

        When an ``idempotency_store`` is configured and the request carries an
        ``idempotency_key`` field, deduplication is enforced:

        - ``"replayed"``  → returns a ManagedRun stub with outcome="replayed".
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
            A ManagedRun with ``outcome`` set to ``"created"`` or ``"replayed"``.
            On ``"replayed"``, ``run_id`` is the original run_id and
            ``response_snapshot`` is the cached response JSON (may be empty when
            the original run is still in-flight).

        Raises:
            ValueError: With message ``"idempotency_conflict"`` when the same
                idempotency key is submitted with a different request payload.
            ValueError: When a run with the same ``task_id`` already exists in
                the workspace.
        """
        idempotency_key: str | None = task_contract_dict.get("idempotency_key")

        # --- body spine precedence under research/prod ----------------
        # Under dev: middleware (workspace) wins for backwards compatibility.
        # Under research/prod: explicit body spine wins; emit DeprecationWarning
        # when body omits tenant_id and we fall back to auth middleware.
        _posture = Posture.from_env()
        _middleware_tenant_id: str = workspace.tenant_id if workspace else ""
        _body_tenant_id: str = task_contract_dict.get("tenant_id", "")
        if _posture.is_strict:
            if _body_tenant_id:
                tenant_id = _body_tenant_id
            else:
                warnings.warn(
                    "body spine required under posture research; falling back to auth middleware. "
                    "This fallback will be removed in Wave 15 (removed if no callers found).",
                    DeprecationWarning,
                    stacklevel=2,
                )
                tenant_id = _middleware_tenant_id or task_contract_dict.get("tenant_id", "default")
        else:
            # dev: middleware wins (backwards compat — RO-1 original behaviour)
            tenant_id = _middleware_tenant_id or _body_tenant_id or "default"

        # --- idempotency check (only when store + key are present) ----------
        outcome: str = ""  # set to "created" | "replayed" | "conflict" when idem is active
        if self._idempotency_store is not None and idempotency_key:
            # Build hash from payload excluding the idempotency_key itself so
            # that the canonical hash represents the actual request content.
            payload_for_hash = {
                k: v for k, v in task_contract_dict.items() if k != "idempotency_key"
            }
            request_hash = _hash_payload(payload_for_hash)
            # Allocate a tentative run_id as UUID4; only used on "created" path.
            candidate_run_id = str(uuid.uuid4())

            # RO-2: pass project_id, user_id, session_id from authenticated workspace.
            outcome, record = self._idempotency_store.reserve_or_replay(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                run_id=candidate_run_id,
                project_id=task_contract_dict.get("project_id", ""),
                user_id=workspace.user_id if workspace else "",
                session_id=workspace.session_id if workspace else "",
            )

            if outcome == "conflict":
                raise ValueError("idempotency_conflict")

            if outcome == "replayed":
                # Return a lightweight stub so the route can inspect outcome and
                # response_snapshot without touching the run registry.
                return ManagedRun(
                    run_id=record.run_id,
                    task_contract=task_contract_dict,
                    outcome="replayed",
                    idempotency_key=idempotency_key,
                    response_snapshot=record.response_snapshot,
                    tenant_id=tenant_id,
                )

            # outcome == "created" — continue with candidate_run_id below.
            run_id = candidate_run_id
        else:
            run_id = str(uuid.uuid4())
            idempotency_key = None

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
            idempotency_key=idempotency_key,
            outcome="created",
        )

        # --- build exec_ctx from resolved spine fields ----------------
        _exec_ctx = RunExecutionContext(
            tenant_id=tenant_id,
            user_id=workspace.user_id if workspace else "",
            session_id=workspace.session_id if workspace else "",
            project_id=task_contract_dict.get("project_id", ""),
            run_id=run_id,
        )

        # --- duplicate task_id check and insertion under the same lock ------
        client_task_id = task_contract_dict.get("task_id", "")
        with self._lock:
            if client_task_id and self._task_id_exists_unlocked(client_task_id, workspace):
                # Clean up orphan idempotency slot reserved above (HIGH-A2).
                if (
                    self._idempotency_store is not None
                    and idempotency_key is not None
                    and outcome == "created"
                ):
                    self._idempotency_store.release(tenant_id, idempotency_key)
                raise ValueError(f"run with task_id '{client_task_id}' already exists in workspace")
            self._runs[run_id] = run

        # --- emit run_queued lifecycle event ---------------------------------
        self._publish_run_event(
            run_id,
            "run_queued",
            {"state": "created", "created_at": now},
            run,
        )

        # --- persist to run_store if available ------------------------------
        if self._run_store is not None:
            import time as _time

            now_ts = _time.time()
            self._run_store.upsert(
                RunRecord(
                    run_id=run_id,
                    tenant_id=tenant_id,  # already authenticated-workspace-derived above
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
                    project_id=task_contract_dict.get("project_id", ""),
                ),
                exec_ctx=_exec_ctx,
            )

        # --- enqueue to durable run_queue if available ----------------------
        if self._run_queue is not None:
            self._run_queue.enqueue(
                run_id=run_id,
                priority=int(task_contract_dict.get("priority", 5)),
                payload_json=json.dumps(task_contract_dict),
            )

        return run

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
            self._active_run_ids.add(run.run_id)
            run.state = "running"
            _started_now = datetime.now(UTC).isoformat()
            run.updated_at = _started_now
            run.started_at = _started_now
        if self._run_store is not None:
            self._run_store.mark_running(run.run_id)
        self._publish_run_event(
            run.run_id,
            "run_started",
            {"state": "running", "started_at": run.updated_at},
            run,
        )
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
            # RO-8: set finished_at on every terminal path so to_dict() always
            # has a non-None value regardless of whether RunResult.finished_at exists.
            _now_iso = datetime.now(UTC).isoformat()
            with self._lock:
                self._active_count -= 1
                self._active_run_ids.discard(run.run_id)
                if run.finished_at is None:
                    run.finished_at = _now_iso
            # Sync terminal state to run_store.
            if self._run_store is not None:
                _result_str = (run.result and str(run.result)) or ""
                if run.state == "completed":
                    self._run_store.mark_complete(run.run_id, _result_str)
                elif run.state == "cancelled":
                    self._run_store.mark_cancelled(run.run_id)
                else:
                    self._run_store.mark_failed(run.run_id, run.error or "")
            self._semaphore.release()
            self._write_trace_stub(run)
            _terminal_event = (
                "run_completed"
                if run.state == "completed"
                else "run_cancelled"
                if run.state == "cancelled"
                else "run_failed"
            )
            self._publish_run_event(
                run.run_id,
                _terminal_event,
                {"state": run.state, "error": run.error or "", "finished_at": run.finished_at},
                run,
            )
            if (
                run.idempotency_key is not None
                and self._idempotency_store is not None
            ):
                # RO-7: map run.state to one of the four canonical terminal codes.
                _terminal = _run_state_to_terminal(run.state)
                self._idempotency_store.mark_complete(
                    run.tenant_id,
                    run.idempotency_key,
                    json.dumps(self.to_dict(run)),
                    terminal_state=_terminal,
                )

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
            self._active_run_ids.add(run.run_id)
            run.state = "running"
            _started_now_d = datetime.now(UTC).isoformat()
            run.updated_at = _started_now_d
            run.started_at = _started_now_d
        if self._run_store is not None:
            self._run_store.mark_running(run.run_id)

        # Start lease renewal daemon thread.
        _heartbeat_stop = threading.Event()

        def _heartbeat_loop() -> None:
            _hb_log = logging.getLogger(__name__)
            interval = (
                self._run_queue.lease_heartbeat_interval_seconds
                if self._run_queue is not None
                else 60.0
            )
            while not _heartbeat_stop.wait(interval):
                try:
                    renewed = self._run_queue.heartbeat(run_id, "run_manager")  # type: ignore[union-attr]
                    if not renewed:
                        _hb_log.warning(
                            "Lease renewal failed for run_id=%s; transitioning to lease_lost state",
                            run_id,
                        )
                        # Transition run state
                        with self._lock:
                            run_obj = self._runs.get(run_id)
                            if run_obj is not None and run_obj.state == "running":
                                run_obj.state = "failed"
                                run_obj.error = "lease_lost: heartbeat renewal denied"
                        # Emit event
                        run_for_event = self._runs.get(run_id)
                        if run_for_event is not None:
                            self._publish_run_event(
                                run_id,
                                "lease_lost",
                                {"reason": "heartbeat_renewal_denied", "state": "failed"},
                                run_for_event,
                            )
                        # Move to DLQ
                        if self._run_queue is not None:
                            try:
                                self._run_queue.dead_letter(
                                    run_id,
                                    "lease_lost",
                                    "running",
                                    tenant_id=getattr(run_for_event, "tenant_id", "") or "",
                                )
                            except Exception as _dlq_exc:
                                _hb_log.warning(
                                    "Failed to dead-letter run_id=%s: %s", run_id, _dlq_exc
                                )
                        # Metric
                        try:
                            from hi_agent.observability.collector import get_metrics_collector
                            get_metrics_collector().increment("hi_agent_runtime_lease_lost_total")
                        except Exception:  # rule7-exempt: metric must not block state transition
                            pass
                        _heartbeat_stop.set()  # stop the heartbeat thread
                except Exception as _hb_exc:
                    _hb_log.warning(
                        "Lease heartbeat error for run_id=%s: %s",
                        run_id,
                        _hb_exc,
                    )

        _heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            daemon=True,
            name=f"lease-heartbeat-{run_id[:8]}",
        )
        if self._run_queue is not None:
            _heartbeat_thread.start()

        self._publish_run_event(
            run_id,
            "run_started",
            {"state": "running", "started_at": run.updated_at},
            run,
        )
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
            # Stop the heartbeat thread before releasing resources.
            _heartbeat_stop.set()
            if self._run_queue is not None:
                _heartbeat_thread.join(timeout=2.0)
            # RO-8: set finished_at on every terminal path (durable path).
            _now_iso_d = datetime.now(UTC).isoformat()
            with self._lock:
                self._active_count -= 1
                self._active_run_ids.discard(run.run_id)
                if run.finished_at is None:
                    run.finished_at = _now_iso_d
            # Sync terminal state to run_store.
            if self._run_store is not None:
                _result_str_d = (run.result and str(run.result)) or ""
                if run.state == "completed":
                    self._run_store.mark_complete(run.run_id, _result_str_d)
                elif run.state == "cancelled":
                    self._run_store.mark_cancelled(run.run_id)
                else:
                    self._run_store.mark_failed(run.run_id, run.error or "")
            self._semaphore.release()
            self._write_trace_stub(run)
            _terminal_event_d = (
                "run_completed"
                if run.state == "completed"
                else "run_cancelled"
                if run.state == "cancelled"
                else "run_failed"
            )
            self._publish_run_event(
                run_id,
                _terminal_event_d,
                {"state": run.state, "error": run.error or "", "finished_at": run.finished_at},
                run,
            )
            if (
                run.idempotency_key is not None
                and self._idempotency_store is not None
            ):
                # RO-7: map run.state to one of the four canonical terminal codes.
                _terminal = _run_state_to_terminal(run.state)
                self._idempotency_store.mark_complete(
                    run.tenant_id,
                    run.idempotency_key,
                    json.dumps(self.to_dict(run)),
                    terminal_state=_terminal,
                )

    @staticmethod
    def _write_trace_stub(run: ManagedRun) -> None:
        """TE-5: Write a stub ReasoningTrace entry to HI_AGENT_DATA_DIR/traces/<run_id>.jsonl.

        Called from the finally block of _execute_run / _execute_run_durable so
        that every completed run leaves a trace file on disk when a data dir is
        configured.  When HI_AGENT_DATA_DIR is not set, the call is a no-op.
        """
        data_dir = os.environ.get("HI_AGENT_DATA_DIR", "").strip()
        if not data_dir:
            return
        try:
            from pathlib import Path

            from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

            traces_dir = Path(data_dir) / "traces"
            traces_dir.mkdir(parents=True, exist_ok=True)
            trace_file = traces_dir / f"{run.run_id}.jsonl"
            entry = ReasoningTraceEntry(
                run_id=run.run_id,
                stage_id=run.current_stage or "unknown",
                step=0,
                kind="placeholder",
                content=f"run terminal state={run.state}",
                metadata={"state": run.state, "error": run.error or ""},
                created_at=datetime.now(UTC).isoformat(),
            )
            with trace_file.open("a", encoding="utf-8") as f:
                import json as _json

                f.write(
                    _json.dumps(
                        {
                            "run_id": entry.run_id,
                            "stage_id": entry.stage_id,
                            "step": entry.step,
                            "kind": entry.kind,
                            "content": entry.content,
                            "metadata": entry.metadata,
                            "created_at": entry.created_at,
                        }
                    )
                    + "\n"
                )
        except Exception as exc:  # trace write must never crash the run lifecycle
            logging.getLogger(__name__).warning(
                "_write_trace_stub: failed to write trace for run_id=%s: %s",
                run.run_id,
                exc,
            )

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
            raise QueueSaturatedError(
                queue_depth=self._queue_size,
                max_depth=self._queue_size,
            ) from None

    def register_cancellation_token(self, run_id: str, token: Any) -> None:
        """Register a CancellationToken for a running executor.

        Called by the executor (or its wrapping closure) once the token is
        constructed, so cancel_run() can signal cooperative cancellation.

        Args:
            run_id: Identifier of the run.
            token: Object with a ``.cancel()`` method (e.g. CancellationToken).
        """
        with self._lock:
            self._active_executor_tokens[run_id] = token

    def unregister_cancellation_token(self, run_id: str) -> None:
        """Remove the CancellationToken registration for a finished run.

        Args:
            run_id: Identifier of the run.
        """
        with self._lock:
            self._active_executor_tokens.pop(run_id, None)

    @property
    def pending_count(self) -> int:
        """Return the number of runs currently waiting in the queue."""
        return self._queue.qsize()

    def queue_depth(self) -> int:
        """Return current number of runs waiting in the in-memory queue."""
        return self._queue.qsize()

    @property
    def max_queue_depth(self) -> int:
        """Return the configured maximum queue depth."""
        return self._queue_size

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
        or ``running`` state. Also signals the durable RunQueue (if wired)
        and the in-process CancellationToken (if registered via
        ``register_cancellation_token``).

        When ``workspace`` is provided, returns False if the run does not
        belong to that workspace.

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
            if run.state not in ("created", "running"):
                return False
            run.state = "cancelled"
            run.updated_at = datetime.now(UTC).isoformat()
        # Propagate to durable queue (cooperative cancellation flag).
        if self._run_queue is not None:
            try:
                self._run_queue.cancel(run_id)
            except Exception as _exc:
                logging.getLogger(__name__).warning(
                    "cancel_run: run_queue.cancel failed for run_id=%s: %s", run_id, _exc
                )
        # Sync cancellation to run_store.
        if self._run_store is not None:
            try:
                self._run_store.mark_cancelled(run_id)
            except Exception as _exc:
                logging.getLogger(__name__).warning(
                    "cancel_run: run_store.mark_cancelled failed for run_id=%s: %s", run_id, _exc
                )
        # Propagate to in-process CancellationToken if one is registered.
        with self._lock:
            token = self._active_executor_tokens.get(run_id)
        if token is not None and hasattr(token, "cancel"):
            try:
                token.cancel()
            except Exception as _exc:
                logging.getLogger(__name__).warning(
                    "cancel_run: token.cancel failed for run_id=%s: %s", run_id, _exc
                )
        return True

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
        # RO-8: fall back to ManagedRun.finished_at so all terminal paths have a value.
        _result = run.result
        _llm_fallback_count: int = 0
        _finished_at: str | None = None
        if _result is not None and hasattr(_result, "llm_fallback_count"):
            _llm_fallback_count = int(_result.llm_fallback_count or 0)
        if _result is not None and hasattr(_result, "finished_at"):
            _finished_at = _result.finished_at
        # RO-8: prefer ManagedRun.finished_at when RunResult is absent (failure, cancel).
        if _finished_at is None:
            _finished_at = run.finished_at
        # Include top-level fallback_events recorded at the server boundary
        # (e.g. route/missing_profile_id events from routes_runs.py).
        # These are keyed on the server-boundary run_id, which differs from the
        # executor's internal run_id used by RunResult.fallback_events.
        from hi_agent.observability.fallback import get_fallback_events as _gfe

        _top_fallback_events: list[dict] = list(_gfe(run.run_id))

        # Liveness fields from event store
        _last_event_offset: int | None = None
        _last_event_at_ts: float | None = None
        if self._event_store is not None:
            try:
                _events = self._event_store.list_since(run.run_id, 0)
                if _events:
                    _last_evt = _events[-1]
                    _last_event_offset = _last_evt.sequence
                    _last_event_at_ts = _last_evt.created_at
            except Exception:
                pass

        _last_event_at: str | None = (
            datetime.fromtimestamp(_last_event_at_ts, tz=UTC).isoformat()
            if _last_event_at_ts is not None
            else None
        )

        # no_progress_seconds: seconds since the most recent heartbeat or event
        _no_progress_seconds: float | None = None
        _candidates: list[float] = []
        if run.last_heartbeat_at is not None:
            with contextlib.suppress(Exception):  # rule7-exempt: ISO timestamp parse for heartbeat age  # noqa: E501
                _candidates.append(
                    datetime.fromisoformat(run.last_heartbeat_at).timestamp()
                )
        if _last_event_at_ts is not None:
            _candidates.append(_last_event_at_ts)
        if _candidates:
            _no_progress_seconds = time.time() - max(_candidates)

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
            # Liveness fields
            "started_at": run.started_at,
            "last_heartbeat_at": run.last_heartbeat_at,
            "last_event_offset": _last_event_offset,
            "last_event_at": _last_event_at,
            "current_action_id": run.current_action_id,
            "no_progress_seconds": _no_progress_seconds,
        }

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop the background worker thread and prevent new queue loops.

        After joining worker threads, any runs still tracked in
        ``_active_run_ids`` are marked failed in the run store and their
        durable RunQueue leases are released so the next process restart can
        recover them via ``_rehydrate_runs``.

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

        # Release leases for runs that did not finish before the deadline.
        with self._lock:
            abandoned = set(self._active_run_ids)
        if abandoned:
            _log = logging.getLogger(__name__)
            _log.warning(
                "shutdown: %d run(s) still active at shutdown — marking failed: %s",
                len(abandoned),
                list(abandoned),
            )
            for _rid in abandoned:
                if self._run_queue is not None:
                    try:
                        self._run_queue.fail(_rid, "run_manager", "server_shutdown")
                    except Exception as _exc:
                        _log.warning(
                            "shutdown: run_queue.fail failed for run_id=%s: %s", _rid, _exc
                        )
                if self._run_store is not None:
                    try:
                        self._run_store.mark_failed(_rid, "server_shutdown")
                    except Exception as _exc:
                        _log.warning(
                            "shutdown: run_store.mark_failed failed for run_id=%s: %s", _rid, _exc
                        )

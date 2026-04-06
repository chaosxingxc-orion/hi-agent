"""Run lifecycle manager for the API server.

Manages creation, execution, querying, and cancellation of runs.
Uses threading for concurrent run execution (stdlib only).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    """Thread-safe run lifecycle manager."""

    def __init__(self, max_concurrent: int = 4) -> None:
        """Initialize the run manager.

        Args:
            max_concurrent: Maximum number of concurrently executing runs.
        """
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)

    def create_run(self, task_contract_dict: dict[str, Any]) -> str:
        """Create a new run from task contract dict.

        Args:
            task_contract_dict: Serialized TaskContract fields.

        Returns:
            The new run_id.
        """
        run_id = task_contract_dict.get("task_id") or uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        run = ManagedRun(
            run_id=run_id,
            task_contract=task_contract_dict,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._runs[run_id] = run
        return run_id

    def start_run(self, run_id: str, executor_fn: Callable[[ManagedRun], Any]) -> None:
        """Start run execution in a background thread.

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

        def _target() -> None:
            acquired = self._semaphore.acquire(timeout=0)
            if not acquired:
                with self._lock:
                    run.state = "failed"
                    run.error = "max_concurrent_exceeded"
                    run.updated_at = datetime.now(timezone.utc).isoformat()
                return
            try:
                with self._lock:
                    run.state = "running"
                    run.updated_at = datetime.now(timezone.utc).isoformat()
                result = executor_fn(run)
                with self._lock:
                    run.state = "completed"
                    run.result = result
                    run.updated_at = datetime.now(timezone.utc).isoformat()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    run.state = "failed"
                    run.error = str(exc)
                    run.updated_at = datetime.now(timezone.utc).isoformat()
            finally:
                self._semaphore.release()

        thread = threading.Thread(target=_target, daemon=True)
        with self._lock:
            run.thread = thread
        thread.start()

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
                run.updated_at = datetime.now(timezone.utc).isoformat()
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

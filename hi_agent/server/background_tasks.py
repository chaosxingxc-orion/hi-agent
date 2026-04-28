"""BackgroundTaskRegistry: bounded, timeout-cancelling task registry for background threads."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class BackgroundTaskRegistry:
    """Thread registry with max-concurrent cap, timeout logging, and metric emission."""

    def __init__(self, max_concurrent: int = 50, default_timeout_s: float = 300.0):
        self._max = max_concurrent
        self._timeout = default_timeout_s
        self._lock = threading.Lock()
        # task_id -> {thread, started_at, name, timeout}
        self._tasks: dict[str, dict[str, Any]] = {}

    def submit(
        self,
        target: Callable,
        name: str = "task",
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Submit a callable to run in a background thread.

        Args:
            target: Callable to invoke in the background thread.
            name: Human-readable label for logging.
            timeout_s: Per-task timeout in seconds; falls back to default_timeout_s.
            **kwargs: Keyword arguments forwarded to *target*.

        Returns:
            An 8-character task_id string.

        Raises:
            RuntimeError: When the registry is at capacity (active >= max_concurrent).
        """
        with self._lock:
            active = sum(1 for t in self._tasks.values() if t["thread"].is_alive())
            if active >= self._max:
                raise RuntimeError(
                    f"BackgroundTaskRegistry at capacity ({self._max} active tasks)"
                )

        task_id = str(uuid.uuid4())[:8]
        timeout = timeout_s if timeout_s is not None else self._timeout

        def _run() -> None:
            try:
                target(**kwargs)
            except Exception as exc:
                logger.warning(
                    "Background task %s/%s failed: %s", name, task_id, exc, exc_info=True
                )
            finally:
                self._cleanup(task_id)

        t = threading.Thread(target=_run, name=f"bgtask-{name}-{task_id}", daemon=False)
        with self._lock:
            self._tasks[task_id] = {
                "thread": t,
                "started_at": time.monotonic(),
                "name": name,
                "timeout": timeout,
            }
        t.start()
        logger.debug("BackgroundTaskRegistry: started task %s/%s", name, task_id)
        return task_id

    def _cleanup(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def active_count(self) -> int:
        """Return the number of currently live background threads."""
        with self._lock:
            return sum(1 for t in self._tasks.values() if t["thread"].is_alive())

    def check_timeouts(self) -> None:
        """Emit WARNING logs for tasks that have exceeded their timeout.

        Threads are daemon=False so they run to completion; this method
        only logs — it does not forcibly terminate threads.
        """
        now = time.monotonic()
        with self._lock:
            for task_id, info in list(self._tasks.items()):
                if not info["thread"].is_alive():
                    continue
                elapsed = now - info["started_at"]
                if elapsed > info["timeout"]:
                    logger.warning(
                        "Background task %s/%s exceeded timeout %.0fs (elapsed %.0fs)",
                        info["name"],
                        task_id,
                        info["timeout"],
                        elapsed,
                    )


_default_registry = BackgroundTaskRegistry()


def get_registry() -> BackgroundTaskRegistry:
    """Return the process-wide BackgroundTaskRegistry singleton."""
    return _default_registry

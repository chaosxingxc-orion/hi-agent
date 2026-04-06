"""Real backend entrypoint for runtime adapter integration."""

from __future__ import annotations

import time
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.kernel_client import KernelClient


class KernelBackend:
    """Production backend adapter that forwards normalized payloads to a client."""

    def __init__(
        self,
        client: KernelClient | None = None,
        *,
        max_retries: int = 0,
        retry_sleep_seconds: float = 0.0,
        retriable_exceptions: tuple[type[Exception], ...] | None = None,
    ) -> None:
        """Initialize backend with client and retry configuration.

        Args:
            client: Optional client implementation.
            max_retries: Number of retries after the first failed attempt.
            retry_sleep_seconds: Delay between retries.
            retriable_exceptions: Exception classes that should trigger retry.
        """
        self.client = client
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.max_retries = max_retries
        self.retry_sleep_seconds = retry_sleep_seconds
        if retriable_exceptions is None:
            # Keep backward compatibility with SimpleKernelClient which
            # normalizes transport errors as RuntimeError.
            self.retriable_exceptions = (TimeoutError, ConnectionError, RuntimeError)
        else:
            self.retriable_exceptions = retriable_exceptions

    def open_stage(self, stage_id: str) -> Any:
        """Forward stage open request as normalized payload."""
        payload = {"stage_id": stage_id}
        return self._forward("open_stage", payload)

    def mark_stage_state(self, stage_id: str, target: StageState) -> Any:
        """Forward stage state update request as normalized payload."""
        payload = {
            "stage_id": stage_id,
            "target": target.value if isinstance(target, StageState) else str(target),
        }
        return self._forward("mark_stage_state", payload)

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> Any:
        """Forward task-view persistence request as normalized payload."""
        payload = {"task_view_id": task_view_id, "content": content}
        return self._forward("record_task_view", payload)

    def _forward(self, operation: str, payload: dict[str, Any]) -> Any:
        """Dispatch payload to client operation, validating availability first."""
        if self.client is None:
            raise RuntimeError(
                f"KernelBackend client is not configured; cannot call '{operation}'."
            )

        handler = getattr(self.client, operation, None)
        if not callable(handler):
            raise RuntimeError(
                f"KernelBackend client missing callable '{operation}' handler."
            )

        attempts = self.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return handler(payload)
            except Exception as exc:
                if not isinstance(exc, self.retriable_exceptions):
                    raise
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(self.retry_sleep_seconds)
                    continue
                break

        if last_error is None:
            raise RuntimeError(
                f"KernelBackend client call did not execute for '{operation}'."
            )
        if isinstance(last_error, RuntimeError):
            raise RuntimeError(
                f"KernelBackend client call failed after {attempts} attempt(s) "
                f"for '{operation}'."
            ) from last_error
        raise last_error

"""Cooperative cancellation token checked at execution boundaries.

A ``CancellationToken`` carries an in-memory flag that any piece of code
can check cheaply.  When a ``RunQueue`` is provided the token also polls
the durable queue record so that cancellation signals survive across thread
boundaries and (when the queue is persisted) across process restarts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.server.run_queue import RunQueue


class RunCancelledError(RuntimeError):
    """Raised when a run is cancelled at a boundary check."""


class CancellationToken:
    """Cooperative cancellation signal checked at execution boundaries.

    The token is considered cancelled when either the in-memory flag is set
    (via :meth:`cancel`) or — when a ``RunQueue`` is provided — the queue
    record carries ``cancellation_flag = 1``.
    """

    def __init__(
        self,
        run_id: str,
        run_queue: RunQueue | None = None,
        tenant_id: str = "",
    ) -> None:
        """Create a cancellation token.

        Args:
            run_id: Identifier of the run this token belongs to.
            run_queue: Optional durable queue.  When provided,
                :attr:`is_cancelled` also consults the queue record.
            tenant_id: Tenant spine — passed through to ``RunQueue.cancel``
                and ``RunQueue.is_cancelled`` so that the durable mutations
                are tenant-scoped per W33 D.2.
        """
        self._run_id = run_id
        self._run_queue = run_queue
        self._tenant_id = tenant_id
        self._cancelled: bool = False

    @property
    def is_cancelled(self) -> bool:
        """Return True if this run has been cancelled.

        Checks the in-memory flag first (cheap), then falls back to the
        queue record when a ``RunQueue`` is available.
        """
        if self._cancelled:
            return True
        if self._run_queue is not None and self._run_queue.is_cancelled(
            self._run_id, tenant_id=self._tenant_id or None
        ):
            self._cancelled = True  # cache the result to avoid repeated DB reads
            return True
        return False

    def cancel(self) -> None:
        """Cancel this token.

        Sets the in-memory flag and, when a ``RunQueue`` is available,
        also sets the durable cancellation flag in the queue record.
        """
        self._cancelled = True
        if self._run_queue is not None:
            self._run_queue.cancel(
                self._run_id, tenant_id=self._tenant_id or None
            )

    def check_or_raise(self) -> None:
        """Raise ``RunCancelledError`` if the run has been cancelled.

        Raises:
            RunCancelledError: When :attr:`is_cancelled` returns ``True``.
        """
        if self.is_cancelled:
            raise RunCancelledError(f"Run {self._run_id} was cancelled")

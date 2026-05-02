"""Graceful shutdown coordinator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Thread


# W31 T-24' decision: in-process shutdown error; tenant-agnostic.
# scope: process-internal
@dataclass(frozen=True)
class ShutdownHookError:
    """Captured error metadata for one hook."""

    hook_name: str
    error_type: str
    error_message: str


# W31 T-24' decision: in-process shutdown hook result; tenant-agnostic.
# scope: process-internal
@dataclass(frozen=True)
class ShutdownHookResult:
    """Execution result for one hook."""

    hook_name: str
    completed: bool
    timed_out: bool
    error: ShutdownHookError | None = None


# W31 T-24' decision: in-process shutdown result; tenant-agnostic.
# scope: process-internal
@dataclass(frozen=True)
class ShutdownResult:
    """Aggregated shutdown execution summary."""

    ok: bool
    total_hooks: int
    completed_hooks: int
    failed_hooks: int
    timed_out_hooks: int
    hook_results: list[ShutdownHookResult]
    errors: list[ShutdownHookError]


# W31 T-24' decision: in-process shutdown manager; tenant-agnostic.
# scope: process-internal
@dataclass
class ShutdownManager:
    """Manage shutdown hooks in deterministic order."""

    hooks: list[Callable[[], None]] = field(default_factory=list)

    def register_hook(self, hook: Callable[[], None]) -> None:
        """Register one shutdown hook."""
        self.hooks.append(hook)

    def run(self, hook_timeout_seconds: float | None = None) -> ShutdownResult:
        """Run hooks in reverse order with timeout and error aggregation."""
        if hook_timeout_seconds is not None and hook_timeout_seconds <= 0:
            msg = "hook_timeout_seconds must be > 0"
            raise ValueError(msg)

        hook_results: list[ShutdownHookResult] = []
        errors: list[ShutdownHookError] = []
        for hook in reversed(self.hooks):
            hook_name = self._hook_name(hook)
            completed, timed_out, error = self._run_hook(
                hook=hook,
                hook_name=hook_name,
                hook_timeout_seconds=hook_timeout_seconds,
            )
            hook_result = ShutdownHookResult(
                hook_name=hook_name,
                completed=completed,
                timed_out=timed_out,
                error=error,
            )
            hook_results.append(hook_result)
            if error is not None:
                errors.append(error)

        total_hooks = len(hook_results)
        completed_hooks = sum(1 for item in hook_results if item.completed)
        timed_out_hooks = sum(1 for item in hook_results if item.timed_out)
        failed_hooks = len(errors)
        return ShutdownResult(
            ok=(failed_hooks == 0 and timed_out_hooks == 0),
            total_hooks=total_hooks,
            completed_hooks=completed_hooks,
            failed_hooks=failed_hooks,
            timed_out_hooks=timed_out_hooks,
            hook_results=hook_results,
            errors=errors,
        )

    def _run_hook(
        self,
        hook: Callable[[], None],
        hook_name: str,
        hook_timeout_seconds: float | None,
    ) -> tuple[bool, bool, ShutdownHookError | None]:
        """Execute one hook and return completion, timeout, and error data."""
        if hook_timeout_seconds is None:
            return self._run_hook_without_timeout(hook=hook, hook_name=hook_name)
        return self._run_hook_with_timeout(
            hook=hook,
            hook_name=hook_name,
            hook_timeout_seconds=hook_timeout_seconds,
        )

    @staticmethod
    def _hook_name(hook: Callable[[], None]) -> str:
        """Derive a stable name for reporting."""
        return getattr(hook, "__name__", hook.__class__.__name__)

    @staticmethod
    def _run_hook_without_timeout(
        hook: Callable[[], None],
        hook_name: str,
    ) -> tuple[bool, bool, ShutdownHookError | None]:
        """Execute one hook without timeout control."""
        try:
            hook()
        except Exception as error:
            return (
                False,
                False,
                ShutdownHookError(
                    hook_name=hook_name,
                    error_type=type(error).__name__,
                    error_message=str(error),
                ),
            )
        return True, False, None

    @staticmethod
    def _run_hook_with_timeout(
        hook: Callable[[], None],
        hook_name: str,
        hook_timeout_seconds: float,
    ) -> tuple[bool, bool, ShutdownHookError | None]:
        """Execute one hook with timeout control."""
        raised_error: list[Exception] = []

        def run_and_capture() -> None:
            try:
                hook()
            except Exception as error:
                raised_error.append(error)

        thread = Thread(target=run_and_capture, daemon=True, name=f"shutdown:{hook_name}")
        thread.start()
        thread.join(timeout=hook_timeout_seconds)
        if thread.is_alive():
            return False, True, None
        if raised_error:
            error = raised_error[0]
            return (
                False,
                False,
                ShutdownHookError(
                    hook_name=hook_name,
                    error_type=type(error).__name__,
                    error_message=str(error),
                ),
            )
        return True, False, None

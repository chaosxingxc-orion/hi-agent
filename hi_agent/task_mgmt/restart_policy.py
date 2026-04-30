"""RestartPolicyEngine: decides whether to retry or escalate a failed task.

TaskRestartPolicy and TaskAttempt are imported from agent-kernel
(single source of truth). TaskAttemptRecord remains as a compatibility alias.
RestartDecision and RestartPolicyEngine are hi-agent's orchestration layer.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from agent_kernel.kernel.task_manager.contracts import (  # noqa: F401  expiry_wave: Wave 26
    ExhaustedPolicy,
    TaskAttempt,
    TaskRestartPolicy,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "RestartAction",
    "RestartDecision",
    "RestartPolicyEngine",
    "TaskAttempt",
    "TaskAttemptRecord",  # noqa: F822 — provided via module __getattr__  expiry_wave: Wave 26
    "TaskRestartPolicy",
]

RestartAction = Literal["retry", "reflect", "escalate", "abort"]


@dataclass(frozen=True)
class RestartDecision:
    """Output of RestartPolicyEngine.decide()."""

    task_id: str
    action: RestartAction
    next_attempt_seq: int | None
    reason: str
    reflection_prompt: str | None = None


def __getattr__(name: str) -> Any:
    """Provide compatibility aliases with explicit deprecation warnings."""
    if name == "TaskAttemptRecord":
        warnings.warn(
            "TaskAttemptRecord is deprecated; use TaskAttempt instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return TaskAttempt
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class RestartPolicyEngine:
    """Decides retry vs reflect vs escalate vs abort for failed/stalled tasks.

    All collaborators are injected as callables so this class has zero
    coupling to registries or facades.
    """

    def __init__(
        self,
        get_attempts: Callable[[str], list[TaskAttempt]],
        get_policy: Callable[[str], TaskRestartPolicy | None],
        update_state: Callable[[str, str], None],
        record_attempt: Callable[[TaskAttempt], None],
        retry_launcher: Callable[[str, int], Awaitable[str | None]] | None = None,
        reflection_handler: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        """Initialize RestartPolicyEngine."""
        self._get_attempts = get_attempts
        self._get_policy = get_policy
        self._update_state = update_state
        self._record_attempt = record_attempt
        self._retry_launcher = retry_launcher
        self._reflection_handler = reflection_handler

    async def handle_failure(
        self,
        task_id: str,
        failed_run_id: str,
        failure: Any | None = None,
        *,
        reflection_run_context: dict[str, Any] | None = None,
    ) -> RestartDecision:
        """Handle a task attempt failure and take the appropriate action.

        Records the attempt failure, evaluates the restart policy, and either
        launches a new run attempt or transitions the task to a terminal state.
        """
        policy = self._get_policy(task_id)
        if policy is None:
            _logger.warning("handle_failure: no policy for task_id=%s", task_id)
            return RestartDecision(
                task_id=task_id,
                action="abort",
                next_attempt_seq=None,
                reason="task_id not found or no restart policy",
            )

        attempts = self._get_attempts(task_id)
        attempt_seq = len(attempts)

        decision = self._decide(policy, task_id, attempt_seq, failure)

        effective_decision = decision
        if decision.action == "retry":
            self._update_state(task_id, "restarting")
            launched = await self._launch_retry(task_id, policy, attempt_seq + 1)
            if not launched:
                effective_decision = replace(
                    decision,
                    action="abort",
                    next_attempt_seq=None,
                    reason=f"{decision.reason}; retry launch failed and task moved to aborted",
                )
                self._update_state(task_id, "aborted")
        elif decision.action == "reflect":
            self._update_state(task_id, "reflecting")
            if self._reflection_handler is not None and reflection_run_context is not None:
                _logger.info(
                    "task.reflection_triggered task_id=%s orchestrator=awaiting",
                    task_id,
                )
                try:
                    await self._reflection_handler(
                        task_id=task_id,
                        attempts=attempts,
                        **reflection_run_context,
                    )
                except Exception as exc:
                    _logger.error(
                        "task.reflection_failed task_id=%s error=%s",
                        task_id,
                        exc,
                    )
        elif decision.action == "escalate":
            self._update_state(task_id, "escalated")
        else:
            self._update_state(task_id, "aborted")

        _logger.info(
            "task.restart_decision task_id=%s action=%s attempt_seq=%d/%d",
            task_id,
            effective_decision.action,
            attempt_seq,
            policy.max_attempts,
        )
        return RestartDecision(
            task_id=task_id,
            action=effective_decision.action,
            next_attempt_seq=effective_decision.next_attempt_seq,
            reason=effective_decision.reason,
        )

    def _decide(
        self,
        policy: TaskRestartPolicy,
        task_id: str,
        attempt_seq: int,
        failure: Any | None,
        stage_id: str = "",
    ) -> RestartDecision:
        """Pure decision logic -- no side effects."""
        retryability = getattr(failure, "retryability", "unknown") if failure else "unknown"
        if retryability == "non_retryable":
            action: RestartAction = policy.on_exhausted  # type: ignore[assignment]  expiry_wave: Wave 26
            return RestartDecision(
                task_id=task_id,
                action=action,
                next_attempt_seq=None,
                reason=(
                    f"failure marked non_retryable: {getattr(failure, 'failure_code', 'unknown')}"
                ),
            )

        failure_reason = (
            (
                getattr(failure, "failure_code", None)
                or getattr(failure, "reason", None)
                or "unknown"
            )
            if failure
            else "unknown"
        )

        if attempt_seq < policy.max_attempts:
            if policy.on_exhausted == "reflect":
                reflection_prompt = (
                    f"Attempt {attempt_seq} failed: {failure_reason}. "
                    f"Stage: {stage_id or 'unknown'}. "
                    f"Identify what went wrong and correct it in the next attempt."
                )
                return RestartDecision(
                    task_id=task_id,
                    action="reflect",
                    next_attempt_seq=attempt_seq + 1,
                    reason=f"attempt {attempt_seq}/{policy.max_attempts} failed; reflecting",
                    reflection_prompt=reflection_prompt,
                )
            return RestartDecision(
                task_id=task_id,
                action="retry",
                next_attempt_seq=attempt_seq + 1,
                reason=f"attempt {attempt_seq}/{policy.max_attempts} failed; retrying",
            )

        on_exhausted = policy.on_exhausted
        reflection_prompt_exhausted: str | None = None
        if on_exhausted == "reflect":
            reflection_prompt_exhausted = (
                f"Previous attempt {attempt_seq} failed: {failure_reason}. "
                f"Stage: {stage_id or 'unknown'}. "
                f"Identify what went wrong and how to correct it in the next attempt."
            )
        return RestartDecision(
            task_id=task_id,
            action=on_exhausted,  # type: ignore[arg-type]  expiry_wave: Wave 26
            next_attempt_seq=None,
            reason=(
                f"retry budget exhausted ({attempt_seq}/{policy.max_attempts}); "
                f"on_exhausted={on_exhausted}"
            ),
            reflection_prompt=reflection_prompt_exhausted,
        )

    async def _launch_retry(
        self,
        task_id: str,
        policy: TaskRestartPolicy,
        next_seq: int,
    ) -> bool:
        """Launch a new Run attempt for this task via the injected retry_launcher."""
        if self._retry_launcher is None:
            _logger.warning("task_manager: no retry_launcher configured; retry skipped")
            return False

        backoff_base = policy.backoff_base_ms
        max_backoff = policy.max_backoff_ms
        delay_ms = min(backoff_base * (2 ** max(0, next_seq - 2)), max_backoff)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        try:
            new_run_id = await self._retry_launcher(task_id, next_seq)
        except Exception as exc:
            _logger.error(
                "task_manager: retry launch failed task_id=%s seq=%d error=%s",
                task_id,
                next_seq,
                exc,
            )
            return False

        if new_run_id is None:
            return False

        attempt = TaskAttempt(
            attempt_id=uuid.uuid4().hex,
            task_id=task_id,
            run_id=new_run_id,
            attempt_seq=next_seq,
            started_at=datetime.now(UTC).isoformat(),
        )
        self._record_attempt(attempt)
        self._update_state(task_id, "restarting")
        _logger.info(
            "task.attempt_started task_id=%s seq=%d run_id=%s",
            task_id,
            next_seq,
            new_run_id,
        )
        return True

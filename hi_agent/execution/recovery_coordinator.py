"""Recovery coordination extracted from RunExecutor (HI-W9-002)."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from hi_agent.gate_protocol import GatePendingError
from hi_agent.observability.metric_counter import Counter
from hi_agent.observability.silent_degradation import record_silent_degradation

_logger = logging.getLogger(__name__)
_recovery_errors_total = Counter("hi_agent_recovery_coordinator_errors_total")


def _reflect_task_done_callback(task: Any) -> None:
    """Log completion or failure of an async reflection background task."""
    if task.cancelled():
        _logger.warning("runner.reflect_async_task_cancelled")
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(
            "runner.reflect_async_task_failed error=%s type=%s",
            exc,
            type(exc).__name__,
        )


@dataclass
class RecoveryContext:
    """State and callbacks required to coordinate recovery."""

    event_emitter: Any
    recovery_executor: Callable[..., object]
    recovery_handlers: Mapping[str, Any] | None
    _recovery_executor_accepts_handlers: bool
    _record_event: Callable[[str, dict], None]
    _log_best_effort_exception: Callable[..., None]
    run_id: str
    _resolve_failed_stage_count: Callable[[object], int | None]
    _run_terminated: bool
    _restart_policy: Any | None
    _stage_attempt: dict[str, int]
    contract: Any
    short_term_store: Any | None
    context_manager: Any | None
    _reflection_orchestrator: Any | None
    _execute_stage: Callable[[str], str | None]
    _get_attempt_history: Callable[[str], list]
    _pending_reflection_tasks: list[object] = field(default_factory=list)


class RecoveryCoordinator:
    """Owns recovery handling extracted from RunExecutor."""

    def __init__(self, ctx: RecoveryContext) -> None:
        self._ctx = ctx

    @staticmethod
    def _parse_forced_fail_actions(constraints: list[str]) -> set[str]:
        """Extract forced-failure action names from constraints.

        Supported format: `fail_action:<action_name>`.
        """
        forced: set[str] = set()
        for item in constraints:
            if not item.startswith("fail_action:"):
                continue
            action_name = item.split(":", 1)[1].strip()
            if action_name:
                forced.add(action_name)
        return forced

    def _resolve_recovery_success(self, report: object) -> bool:
        """Extract normalized success flag from recovery report payload."""
        if isinstance(report, dict):
            return bool(report.get("success", True))

        if hasattr(report, "success"):
            return bool(report.success)

        if hasattr(report, "execution_report") and hasattr(report.execution_report, "success"):
            return bool(report.execution_report.success)

        return True

    def _resolve_recovery_should_escalate(self, report: object) -> bool | None:
        """Extract optional escalation signal from recovery report payload."""
        if isinstance(report, dict) and "should_escalate" in report:
            return bool(report["should_escalate"])

        if hasattr(report, "should_escalate"):
            return bool(report.should_escalate)

        return None

    def _trigger_recovery(self, stage_id: str) -> None:
        """Execute recovery hook and emit recovery lifecycle events."""
        self._ctx._record_event("RecoveryTriggered", {"stage_id": stage_id})
        consumed_events = tuple(self._ctx.event_emitter.events)
        success = False
        report: object | None = None

        try:
            if self._ctx._recovery_executor_accepts_handlers:
                report = self._ctx.recovery_executor(consumed_events, self._ctx.recovery_handlers)
            else:
                report = self._ctx.recovery_executor(consumed_events)
            success = self._resolve_recovery_success(report)
        except Exception as exc:
            _recovery_errors_total.inc()
            success = False
            self._ctx._log_best_effort_exception(
                logging.WARNING,
                "runner.recovery_failed",
                exc,
                run_id=self._ctx.run_id,
                stage_id=stage_id,
            )

        payload: dict[str, object] = {
            "stage_id": stage_id,
            "success": success,
        }
        if report is not None:
            should_escalate = self._resolve_recovery_should_escalate(report)
            if should_escalate is not None:
                payload["should_escalate"] = should_escalate
            failed_stage_count = self._ctx._resolve_failed_stage_count(report)
            if failed_stage_count is not None:
                payload["failed_stage_count"] = failed_stage_count

        self._ctx._record_event(
            "RecoveryCompleted",
            payload,
        )

    def _handle_stage_failure(
        self,
        stage_id: str,
        stage_result: str,
        *,
        max_retries: int = 3,
    ) -> str:
        """Decide how to handle a stage failure using RestartPolicyEngine.

        When no RestartPolicyEngine is configured the method returns "failed"
        immediately, preserving the original behaviour.  When an engine is
        present it queries ``engine.decide(...)`` and acts on the decision:

        * retry   — re-execute the stage (up to *max_retries* times)
        * reflect — run ReflectionOrchestrator then continue
        * escalate — log the escalation and return "failed"
        * abort   — return "failed" immediately

        All new logic is wrapped in try/except so any error falls back to the
        original "failed" path.
        """
        # Honour a backtrack gate decision: run is terminated, no retry or reflect.
        if self._ctx._run_terminated:
            _logger.info(
                "runner.stage_failure_skipped_terminated stage_id=%s run_id=%s",
                stage_id,
                self._ctx.run_id,
            )
            return "failed"

        if self._ctx._restart_policy is None:
            return "failed"

        # K-7: hard safety ceiling against unbounded recursion
        _max_total_attempts = max_retries * 2 + 1
        try:
            for _loop_guard in range(_max_total_attempts):
                attempt = self._ctx._stage_attempt.get(stage_id, 0) + 1
                self._ctx._stage_attempt[stage_id] = attempt

                # Build a lightweight failure object the engine can inspect.
                class _StageFail:
                    retryability = "unknown"
                    failure_code = stage_result

                policy_task_id = self._ctx.contract.task_id

                # Record this attempt so reflect_and_infer() receives real history.
                try:
                    from datetime import UTC, datetime

                    from hi_agent.task_mgmt.restart_policy import TaskAttempt

                    _ta_kwargs: dict = {
                        "attempt_id": f"{self._ctx.run_id}/{stage_id}/{attempt}",
                        "task_id": policy_task_id,
                        "run_id": self._ctx.run_id,
                        "attempt_seq": attempt,
                        "started_at": datetime.now(UTC).isoformat(),
                        "outcome": "failed",
                        "failure": _StageFail(),
                    }
                    # stage_id was added in H-1; fall back gracefully if absent.
                    try:
                        ta_obj = TaskAttempt(**_ta_kwargs, stage_id=stage_id)
                    except TypeError:
                        ta_obj = TaskAttempt(**_ta_kwargs)
                        with contextlib.suppress(AttributeError, TypeError):
                            object.__setattr__(ta_obj, "stage_id", stage_id)
                    self._ctx._restart_policy._record_attempt(ta_obj)
                except Exception as _rec_exc:
                    _recovery_errors_total.inc()
                    _logger.debug(
                        "runner.record_attempt_failed stage_id=%s attempt=%d error=%s",
                        stage_id,
                        attempt,
                        _rec_exc,
                    )

                _policy = self._ctx._restart_policy._get_policy(policy_task_id)
                if _policy is None:
                    _logger.warning(
                        "runner: no restart policy for task_id=%s, defaulting to abort",
                        policy_task_id,
                    )
                    from hi_agent.task_mgmt.restart_policy import RestartDecision

                    decision = RestartDecision(
                        task_id=policy_task_id,
                        action="abort",
                        next_attempt_seq=None,
                        reason="no restart policy configured",
                    )
                else:
                    decision = self._ctx._restart_policy._decide(
                        _policy,
                        policy_task_id,
                        attempt,
                        _StageFail(),
                        stage_id=stage_id,
                    )

                _logger.info(
                    "runner.restart_decision stage_id=%s attempt=%d action=%s reason=%s",
                    stage_id,
                    attempt,
                    decision.action,
                    decision.reason,
                )

                if decision.action == "retry":
                    if attempt <= max_retries:
                        _logger.info(
                            "runner.stage_retry stage_id=%s attempt=%d/%d",
                            stage_id,
                            attempt,
                            max_retries,
                        )
                        retry_result = self._ctx._execute_stage(stage_id)
                        if retry_result != "failed":
                            return retry_result
                        stage_result = retry_result
                        continue  # K-7: loop back instead of recursing
                    _logger.warning(
                        "runner.stage_retry_exhausted stage_id=%s max_retries=%d",
                        stage_id,
                        max_retries,
                    )
                    return "failed"

                if decision.action == "reflect":
                    # Pinned retrieval: load prior reflection prompt by exact
                    # session_id to bypass list_recent() window limits.
                    # Best-effort — retry proceeds if unavailable.
                    if self._ctx.short_term_store is not None and attempt > 1:
                        try:
                            prior_session = f"{self._ctx.run_id}/reflect/{stage_id}/{attempt - 1}"
                            prior_mem = self._ctx.short_term_store.load(prior_session)
                            if prior_mem is not None and self._ctx.context_manager is not None:
                                self._ctx.context_manager.set_reflection_context(
                                    prior_mem.task_goal or ""
                                )
                        except Exception as exc:
                            record_silent_degradation(
                                component="execution.recovery_coordinator.RecoveryCoordinator._load_prior_reflection",
                                reason="load_prior_session_failed",
                                exc=exc,
                            )

                    # Inject reflection prompt into the run context so the next
                    # stage attempt has actionable guidance from the failure.
                    if decision.reflection_prompt is not None:
                        try:
                            self._ctx._record_event(
                                "ReflectionPrompt",
                                {
                                    "stage_id": stage_id,
                                    "run_id": self._ctx.run_id,
                                    "reflection_prompt": decision.reflection_prompt,
                                },
                            )
                        except Exception as exc:
                            _recovery_errors_total.inc()
                            _logger.warning(
                                "runner.reflect_prompt_record_failed stage_id=%s error=%s",
                                stage_id,
                                exc,
                            )
                    if self._ctx._reflection_orchestrator is not None:
                        try:
                            import asyncio

                            descriptor_cls = None
                            try:
                                from hi_agent.task_mgmt.reflection_bridge import (
                                    TaskDescriptor,
                                )

                                descriptor_cls = TaskDescriptor
                            except Exception as exc:
                                _recovery_errors_total.inc()
                                _logger.warning(
                                    "runner: task_descriptor import failed, reflection skipped: %s",
                                    exc,
                                )

                            if descriptor_cls is not None:
                                descriptor = descriptor_cls(
                                    task_id=policy_task_id,
                                    goal=getattr(self._ctx.contract, "goal", ""),
                                    context={},
                                )
                                loop = None
                                # No running event loop in this thread means
                                # we can use asyncio.run below.
                                try:
                                    loop = asyncio.get_running_loop()
                                except RuntimeError as _exc:
                                    if "no running event loop" not in str(_exc).lower():
                                        from hi_agent.observability.silent_degradation import (
                                            record_silent_degradation,
                                        )

                                        _ctx = getattr(self, "_ctx", None)
                                        record_silent_degradation(
                                            component="recovery_coordinator.close_loop",
                                            reason="get_running_loop_unexpected_error",
                                            run_id=getattr(_ctx, "run_id", None),
                                            exc=_exc,
                                        )

                                if loop is not None and loop.is_running():
                                    # Save reflection prompt synchronously — must
                                    # precede the retry LLM call.
                                    if (
                                        decision.reflection_prompt
                                        and self._ctx.short_term_store is not None
                                    ):
                                        try:
                                            from hi_agent.memory.short_term import (
                                                ShortTermMemory,
                                            )

                                            self._ctx.short_term_store.save(
                                                ShortTermMemory(
                                                    session_id=f"{self._ctx.run_id}/reflect/{stage_id}/{attempt}",
                                                    run_id=self._ctx.run_id,
                                                    task_goal=decision.reflection_prompt,
                                                    outcome="reflecting",
                                                )
                                            )
                                        except Exception as _exc:
                                            _recovery_errors_total.inc()
                                            _logger.warning(
                                                "runner.reflect_context_inject_failed "
                                                "stage_id=%s error=%s",
                                                stage_id,
                                                _exc,
                                            )
                                    # Fire extended LLM reflection as a background task.
                                    task = loop.create_task(
                                        self._ctx._reflection_orchestrator.reflect_and_infer(
                                            descriptor=descriptor,
                                            attempts=self._ctx._get_attempt_history(stage_id),
                                            run_id=self._ctx.run_id,
                                        )
                                    )
                                    task.add_done_callback(_reflect_task_done_callback)
                                    self._ctx._pending_reflection_tasks.append(
                                        task
                                    )  # J8-1: track for finalization
                                    _logger.info(
                                        "runner.reflect_scheduled_async stage_id=%s",
                                        stage_id,
                                    )
                                else:
                                    # Rule 12: route through the durable
                                    # SyncBridge so reflection's async
                                    # resources share one event loop.
                                    from hi_agent.runtime.sync_bridge import (
                                        get_bridge,
                                    )

                                    get_bridge().call_sync(
                                        self._ctx._reflection_orchestrator.reflect_and_infer(
                                            descriptor=descriptor,
                                            attempts=self._ctx._get_attempt_history(stage_id),
                                            run_id=self._ctx.run_id,
                                        )
                                    )
                                    # Inject reflection prompt into short-term
                                    # memory so retry LLM sees it.
                                    if (
                                        decision.reflection_prompt
                                        and self._ctx.short_term_store is not None
                                    ):
                                        try:
                                            from hi_agent.memory.short_term import (
                                                ShortTermMemory,
                                            )

                                            self._ctx.short_term_store.save(
                                                ShortTermMemory(
                                                    session_id=f"{self._ctx.run_id}/reflect/{stage_id}/{attempt}",
                                                    run_id=self._ctx.run_id,
                                                    task_goal=decision.reflection_prompt,
                                                    outcome="reflecting",
                                                )
                                            )
                                        except Exception as _exc:
                                            _recovery_errors_total.inc()
                                            _logger.warning(
                                                "runner.reflect_context_inject_failed "
                                                "stage_id=%s error=%s",
                                                stage_id,
                                                _exc,
                                            )
                        except Exception as exc:
                            _recovery_errors_total.inc()
                            _logger.warning(
                                "runner.reflect_failed stage_id=%s error=%s",
                                stage_id,
                                exc,
                            )
                    else:
                        _logger.info(
                            "runner.reflect_no_orchestrator stage_id=%s",
                            stage_id,
                        )
                    # If a next attempt is scheduled (reflect-before-retry), run it now.
                    if decision.next_attempt_seq is not None:
                        _logger.info(
                            "runner.reflect_retry stage_id=%s next_attempt=%d",
                            stage_id,
                            decision.next_attempt_seq,
                        )
                        retry_result = self._ctx._execute_stage(stage_id)
                        if retry_result != "failed":
                            return retry_result
                        stage_result = retry_result
                        continue  # K-7: loop back instead of recursing
                    # Budget exhausted after reflection — do not propagate failure.
                    return "reflected"

                if decision.action == "escalate":
                    _logger.warning(
                        "runner.stage_escalated stage_id=%s run_id=%s",
                        stage_id,
                        self._ctx.run_id,
                    )
                    try:
                        self._ctx._record_event(
                            "StageEscalated",
                            {
                                "stage_id": stage_id,
                                "run_id": self._ctx.run_id,
                                "reason": decision.reason,
                            },
                        )
                    except Exception as exc:
                        _recovery_errors_total.inc()
                        _logger.warning(
                            "runner: StageEscalated event recording failed, continuing: %s", exc
                        )
                    return "failed"

                # action == "abort" or unknown
                _logger.info(
                    "runner.stage_aborted stage_id=%s run_id=%s",
                    stage_id,
                    self._ctx.run_id,
                )
                return "failed"

            _logger.warning(
                "runner.stage_failure_loop_ceiling stage_id=%s run_id=%s ceiling=%d",
                stage_id,
                self._ctx.run_id,
                _max_total_attempts,
            )
            return "failed"

        except GatePendingError:
            raise  # gate must propagate — not a retry failure

        except Exception as exc:
            _recovery_errors_total.inc()
            _logger.warning(
                "runner.handle_stage_failure_error stage_id=%s error=%s — falling back to failed",
                stage_id,
                exc,
            )
            return "failed"

"""Stage traversal orchestrator extracted from RunExecutor (HI-W10-001).

Provides three traversal strategies (linear, graph, resume) and a shared
exception-handling + finalization wrapper.  RunExecutor's three public entry
points (execute, execute_graph, _execute_remaining) become thin facades that
build a StageOrchestratorContext and delegate here.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hi_agent.gate_protocol import GatePendingError
from hi_agent.observability.silent_degradation import record_silent_degradation
from hi_agent.observability.spine_events import (
    emit_stage_inserted,
    emit_stage_replanned,
    emit_stage_skipped,
)

_logger = logging.getLogger(__name__)


@dataclass
class StageOrchestratorContext:
    """All references needed by StageOrchestrator to run stage loops."""

    # --- Identity & contract ---
    run_id: str
    contract: Any

    # --- Graph & state ---
    stage_graph: Any
    stage_summaries: dict
    policy_versions: Any
    session: Any | None
    route_engine: Any

    # --- Optional components ---
    metrics_collector: Any | None
    replan_hook: Any | None  # optional StageDirective hook

    # --- Bound methods from RunExecutor ---
    execute_stage_fn: Callable[[str], str | None]
    handle_stage_failure_fn: Callable[..., str]
    finalize_run_fn: Callable[[str], Any]
    emit_observability_fn: Callable[[str, dict], None]
    log_best_effort_fn: Callable[..., None]
    record_event_fn: Callable[[str, dict], None]
    # Sets an attribute on RunExecutor by name (for _last_exception_msg etc.)
    set_executor_attr_fn: Callable[[str, Any], None]


class StageOrchestrator:
    """Executes the stage traversal loop for RunExecutor.

    Three strategies are available:
    - ``run_linear()``:  deterministic trace_order() traversal (execute())
    - ``run_graph()``:   dynamic successor-based traversal (execute_graph())
    - ``run_resume()``:  skip already-completed stages (_execute_remaining())

    All three share the same GatePendingError propagation and exception
    capture semantics via ``_run_loop()``.
    """

    def __init__(self, ctx: StageOrchestratorContext) -> None:
        self._ctx = ctx

    # ------------------------------------------------------------------
    # Public traversal entry points
    # ------------------------------------------------------------------

    def run_linear(self) -> Any:
        """Linear execution: iterate trace_order(), handle failures."""
        ctx = self._ctx
        self._start_run_preamble()

        def _traverse():
            remaining_stages: list[str] = list(ctx.stage_graph.trace_order())
            while remaining_stages:
                stage_id = remaining_stages.pop(0)
                stage_result = self._execute_stage_with_events(stage_id)
                if stage_result == "failed":
                    handled = ctx.handle_stage_failure_fn(stage_id, stage_result)
                    if handled == "failed":
                        yield ("finalize", "failed")
                        return
                # replan hook
                if ctx.replan_hook is not None:
                    try:
                        from hi_agent.config.posture import Posture
                        from hi_agent.contracts.directives import StageDirective
                        from hi_agent.contracts.exceptions import StageDirectiveError

                        _stage_result_dict = stage_result if isinstance(stage_result, dict) else {}
                        directive = ctx.replan_hook(stage_id, _stage_result_dict)
                        if (
                            directive is not None
                            and isinstance(directive, StageDirective)
                            and directive.action != "continue"
                        ):
                            _logger.info(
                                "replan_hook directive: %s (reason=%s)",
                                directive.action,
                                directive.reason,
                            )
                            if directive.action == "skip" and directive.target_stage_id:
                                remaining_stages = [
                                    s for s in remaining_stages if s != directive.target_stage_id
                                ]
                                with contextlib.suppress(Exception):
                                    emit_stage_skipped(
                                        ctx.run_id,
                                        stage_id,
                                        directive.target_stage_id,
                                        posture=Posture.from_env().name,
                                        reason=directive.reason,
                                    )
                            elif directive.action == "repeat":
                                remaining_stages.insert(0, stage_id)
                                with contextlib.suppress(Exception):
                                    emit_stage_replanned(
                                        ctx.run_id,
                                        "repeat",
                                        stage_id,
                                        stage_id,
                                        posture=Posture.from_env().name,
                                        reason=directive.reason,
                                    )
                            elif directive.action == "insert":
                                _posture = Posture.from_env()
                                for spec in directive.insert:
                                    if spec.target_stage_id in remaining_stages:
                                        anchor_idx = remaining_stages.index(spec.target_stage_id)
                                        remaining_stages.insert(anchor_idx + 1, spec.new_stage)
                                        with contextlib.suppress(Exception):
                                            emit_stage_inserted(
                                                ctx.run_id,
                                                spec.target_stage_id,
                                                spec.new_stage,
                                                posture=_posture.name,
                                                reason=directive.reason,
                                            )
                                    else:
                                        if _posture.is_strict:
                                            raise StageDirectiveError(
                                                "insert anchor"
                                                f" target_stage_id={spec.target_stage_id!r}"
                                                " not found in remaining stages"
                                            )
                                        _logger.warning(
                                            "insert anchor %r not found in remaining stages"
                                            " (dev posture — appending at tail)",
                                            spec.target_stage_id,
                                        )
                                        remaining_stages.append(spec.new_stage)
                                        with contextlib.suppress(Exception):
                                            emit_stage_inserted(
                                                ctx.run_id,
                                                spec.target_stage_id,
                                                spec.new_stage,
                                                posture=_posture.name,
                                                reason=directive.reason,
                                            )
                            elif directive.action == "skip_to":
                                _posture = Posture.from_env()
                                if directive.skip_to in remaining_stages:
                                    target_idx = remaining_stages.index(directive.skip_to)
                                    remaining_stages = remaining_stages[target_idx:]
                                    with contextlib.suppress(Exception):
                                        emit_stage_replanned(
                                            ctx.run_id,
                                            "skip_to",
                                            stage_id,
                                            directive.skip_to,
                                            posture=_posture.name,
                                            reason=directive.reason,
                                        )
                                else:
                                    if _posture.is_strict:
                                        raise StageDirectiveError(
                                            f"skip_to target {directive.skip_to!r}"
                                            " not in remaining stages"
                                        )
                                    _logger.warning(
                                        "skip_to %r ignored (dev posture, unknown stage)",
                                        directive.skip_to,
                                    )
                    except StageDirectiveError:
                        raise
                    except Exception as exc:
                        ctx.log_best_effort_fn(
                            logging.DEBUG,
                            "stage_orchestrator.replan_hook_failed",
                            exc,
                            run_id=ctx.run_id,
                        )
            yield ("finalize", "completed")

        return self._run_loop(_traverse())

    def run_graph(self) -> Any:
        """Graph-based execution: follow successors() dynamically."""
        ctx = self._ctx
        self._start_run_preamble()

        current_stage = self._find_start_stage()
        completed_stages: set[str] = set()
        max_steps = len(ctx.stage_graph.transitions) * 2

        def _traverse():
            nonlocal current_stage
            steps = 0
            while current_stage is not None and steps < max_steps:
                steps += 1
                result = self._execute_stage_with_events(current_stage)
                if result == "failed":
                    backtrack = ctx.stage_graph.get_backtrack(current_stage)
                    if backtrack and backtrack not in completed_stages:
                        current_stage = backtrack
                        continue
                    handled = ctx.handle_stage_failure_fn(current_stage, result)
                    if handled == "failed":
                        yield ("finalize", "failed")
                        return
                completed_stages.add(current_stage)

                # Consult replan_hook between node executions
                if ctx.replan_hook is not None:
                    try:
                        from hi_agent.config.posture import Posture
                        from hi_agent.contracts.directives import StageDirective
                        from hi_agent.contracts.exceptions import StageDirectiveError

                        _result_dict = result if isinstance(result, dict) else {}
                        directive = ctx.replan_hook(current_stage, _result_dict)
                        if (
                            directive is not None
                            and isinstance(directive, StageDirective)
                            and directive.action != "continue"
                        ):
                            _logger.info(
                                "graph replan_hook directive: %s (reason=%s)",
                                directive.action,
                                directive.reason,
                            )
                            if directive.action == "skip_to":
                                _posture = Posture.from_env()
                                if directive.skip_to in ctx.stage_graph.transitions:
                                    with contextlib.suppress(Exception):
                                        emit_stage_replanned(
                                            ctx.run_id,
                                            "skip_to",
                                            current_stage,
                                            directive.skip_to,
                                            posture=_posture.name,
                                            reason=directive.reason,
                                        )
                                    current_stage = directive.skip_to
                                    continue
                                elif _posture.is_strict:
                                    raise StageDirectiveError(
                                        f"skip_to {directive.skip_to!r} not in graph nodes"
                                    )
                                # dev posture — ignore and continue normally
                            elif directive.action == "insert":
                                for spec in directive.insert:
                                    _logger.info(
                                        "graph_directive: inserting stage %r after %r",
                                        spec.new_stage,
                                        current_stage,
                                    )
                                    with contextlib.suppress(Exception):
                                        emit_stage_inserted(
                                            ctx.run_id,
                                            current_stage,
                                            spec.new_stage,
                                            posture=Posture.from_env().name,
                                            reason=directive.reason,
                                        )
                                    # Full in-line injection deferred to M.5; log intent now
                            elif directive.action == "skip":
                                # Skip the next natural successor
                                successors = ctx.stage_graph.successors(current_stage)
                                candidates = successors - completed_stages
                                if candidates:
                                    next_natural = (
                                        next(iter(candidates))
                                        if len(candidates) == 1
                                        else self._select_next_stage(candidates)
                                    )
                                    # Mark the next stage as completed to skip it
                                    completed_stages.add(next_natural)
                                    with contextlib.suppress(Exception):
                                        emit_stage_skipped(
                                            ctx.run_id,
                                            current_stage,
                                            next_natural,
                                            posture=Posture.from_env().name,
                                            reason=directive.reason,
                                        )
                            # "repeat" not naturally supported in graph mode
                    except StageDirectiveError:
                        raise
                    except Exception as exc:
                        ctx.log_best_effort_fn(
                            logging.DEBUG,
                            "stage_orchestrator.graph_replan_hook_failed",
                            exc,
                            run_id=ctx.run_id,
                        )

                successors = ctx.stage_graph.successors(current_stage)
                candidates = successors - completed_stages
                if not candidates:
                    break
                if len(candidates) == 1:
                    current_stage = next(iter(candidates))
                else:
                    current_stage = self._select_next_stage(candidates)
            yield ("finalize", "completed")

        return self._run_loop(_traverse())

    def run_resume(self) -> Any:
        """Resume execution: skip already-completed stages, then consult replan_hook."""
        ctx = self._ctx

        completed_stages: set[str] = set()
        if ctx.session is not None:
            completed_stages = {
                sid for sid, state in ctx.session.stage_states.items() if state == "completed"
            }
        else:
            completed_stages = {
                sid
                for sid, summary in ctx.stage_summaries.items()
                if getattr(summary, "outcome", None) in ("completed", "success")
            }

        ctx.emit_observability_fn(
            "run_resumed",
            {
                "run_id": ctx.run_id,
                "completed_stages": sorted(completed_stages),
                "resuming_from": getattr(ctx.session, "current_stage", None),
            },
        )

        all_completed = True

        def _traverse():
            nonlocal all_completed
            # Build remaining_stages list: trace_order minus already-completed
            remaining_stages: list[str] = []
            for stage_id in ctx.stage_graph.trace_order():
                if stage_id in completed_stages:
                    ctx.emit_observability_fn(
                        "stage_skipped_resume",
                        {
                            "run_id": ctx.run_id,
                            "stage_id": stage_id,
                        },
                    )
                else:
                    remaining_stages.append(stage_id)

            if not remaining_stages:
                yield ("finalize", "completed")
                return

            all_completed = False

            while remaining_stages:
                stage_id = remaining_stages.pop(0)
                stage_result = self._execute_stage_with_events(stage_id)
                if stage_result == "failed":
                    handled = ctx.handle_stage_failure_fn(stage_id, stage_result)
                    if handled == "failed":
                        yield ("finalize", "failed")
                        return

                # Consult replan_hook after each stage, before continuing replay
                if ctx.replan_hook is not None:
                    try:
                        from hi_agent.config.posture import Posture
                        from hi_agent.contracts.directives import StageDirective
                        from hi_agent.contracts.exceptions import StageDirectiveError

                        _result_dict = stage_result if isinstance(stage_result, dict) else {}
                        directive = ctx.replan_hook(stage_id, _result_dict)
                        if (
                            directive is not None
                            and isinstance(directive, StageDirective)
                            and directive.action != "continue"
                        ):
                            _logger.info(
                                "resume replan_hook directive: %s (reason=%s)",
                                directive.action,
                                directive.reason,
                            )
                            if directive.action == "skip_to":
                                _posture = Posture.from_env()
                                if directive.skip_to in remaining_stages:
                                    target_idx = remaining_stages.index(directive.skip_to)
                                    remaining_stages = remaining_stages[target_idx:]
                                    with contextlib.suppress(Exception):
                                        emit_stage_replanned(
                                            ctx.run_id,
                                            "skip_to",
                                            stage_id,
                                            directive.skip_to,
                                            posture=_posture.name,
                                            reason=directive.reason,
                                        )
                                else:
                                    if _posture.is_strict:
                                        raise StageDirectiveError(
                                            f"skip_to {directive.skip_to!r}"
                                            " not in resume stages"
                                        )
                                    _logger.warning(
                                        "resume skip_to %r ignored (dev posture, unknown stage)",
                                        directive.skip_to,
                                    )
                            elif directive.action == "insert":
                                _posture = Posture.from_env()
                                for spec in directive.insert:
                                    if spec.target_stage_id in remaining_stages:
                                        anchor_idx = remaining_stages.index(spec.target_stage_id)
                                        remaining_stages.insert(anchor_idx + 1, spec.new_stage)
                                        with contextlib.suppress(Exception):
                                            emit_stage_inserted(
                                                ctx.run_id,
                                                spec.target_stage_id,
                                                spec.new_stage,
                                                posture=_posture.name,
                                                reason=directive.reason,
                                            )
                                    else:
                                        if _posture.is_strict:
                                            raise StageDirectiveError(
                                                "insert anchor"
                                                f" target_stage_id={spec.target_stage_id!r}"
                                                " not found in resume stages"
                                            )
                                        _logger.warning(
                                            "resume insert anchor %r not found"
                                            " (dev posture — appending at tail)",
                                            spec.target_stage_id,
                                        )
                                        remaining_stages.append(spec.new_stage)
                                        with contextlib.suppress(Exception):
                                            emit_stage_inserted(
                                                ctx.run_id,
                                                spec.target_stage_id,
                                                spec.new_stage,
                                                posture=_posture.name,
                                                reason=directive.reason,
                                            )
                    except StageDirectiveError:
                        raise
                    except Exception as exc:
                        ctx.log_best_effort_fn(
                            logging.DEBUG,
                            "stage_orchestrator.resume_replan_hook_failed",
                            exc,
                            run_id=ctx.run_id,
                        )

            yield ("finalize", "completed")

        result = self._run_loop(_traverse())

        if all_completed:
            ctx.emit_observability_fn("run_already_completed", {"run_id": ctx.run_id})

        return result

    # ------------------------------------------------------------------
    # Shared loop infrastructure
    # ------------------------------------------------------------------

    def _execute_stage_with_events(self, stage_id: str) -> str | None:
        """Wrap execute_stage_fn with stage_start/stage_complete event publishing."""
        ctx = self._ctx
        try:
            ctx.record_event_fn("stage_start", {"stage_name": stage_id})
        except Exception as exc:
            record_silent_degradation(
                component="execution.stage_orchestrator.StageOrchestrator._execute_stage_with_events",
                reason="record_stage_start_event_failed",
                exc=exc,
            )
        result = ctx.execute_stage_fn(stage_id)
        try:
            ctx.record_event_fn(
                "stage_complete",
                {
                    "stage_name": stage_id,
                    "status": "failed" if result == "failed" else "success",
                },
            )
        except Exception as exc:
            record_silent_degradation(
                component="execution.stage_orchestrator.StageOrchestrator._execute_stage_with_events",
                reason="record_stage_complete_event_failed",
                exc=exc,
            )
        return result

    def _start_run_preamble(self) -> None:
        """Record RunStarted event and metrics; set _run_start_monotonic."""
        ctx = self._ctx
        ctx.record_event_fn(
            "RunStarted",
            {
                "run_id": ctx.run_id,
                "task_id": ctx.contract.task_id,
                "policy_versions": {
                    "route_policy": ctx.policy_versions.route_policy,
                    "acceptance_policy": ctx.policy_versions.acceptance_policy,
                    "memory_policy": ctx.policy_versions.memory_policy,
                    "evaluation_policy": ctx.policy_versions.evaluation_policy,
                    "task_view_policy": ctx.policy_versions.task_view_policy,
                    "skill_policy": ctx.policy_versions.skill_policy,
                },
            },
        )
        if ctx.metrics_collector is not None:
            try:
                ctx.metrics_collector.increment("runs_active", 1.0)
            except Exception as exc:
                ctx.log_best_effort_fn(
                    logging.DEBUG,
                    "runner.metrics_increment_failed",
                    exc,
                    run_id=ctx.run_id,
                )
        ctx.set_executor_attr_fn("_run_start_monotonic", time.monotonic())

    def _run_loop(self, traversal) -> Any:
        """Drive traversal generator; handle GatePendingError + generic exceptions."""
        from hi_agent.contracts.exceptions import StageDirectiveError

        ctx = self._ctx
        try:
            for signal, outcome in traversal:
                if signal == "finalize":
                    return ctx.finalize_run_fn(outcome)
        except GatePendingError:
            raise  # propagate — gate awaits human input
        except StageDirectiveError:
            raise  # propagate — strict posture directive failure must surface
        except Exception as exc:
            ctx.set_executor_attr_fn("_last_exception_msg", str(exc))
            ctx.set_executor_attr_fn("_last_exception_type", type(exc).__name__)
            ctx.log_best_effort_fn(
                logging.WARNING,
                "stage_orchestrator.loop_failed",
                exc,
                run_id=ctx.run_id,
            )
            ctx.record_event_fn("RunError", {"error": str(exc), "run_id": ctx.run_id})
            return ctx.finalize_run_fn("failed")
        # traversal ended without yielding finalize (empty graph?)
        return ctx.finalize_run_fn("completed")

    # ------------------------------------------------------------------
    # Graph helpers
    # ------------------------------------------------------------------

    def _find_start_stage(self) -> str | None:
        """Find the zero-indegree start stage from stage_graph."""
        ctx = self._ctx
        if not ctx.stage_graph.transitions:
            return None
        indegree: dict[str, int] = dict.fromkeys(ctx.stage_graph.transitions, 0)
        for targets in ctx.stage_graph.transitions.values():
            for t in targets:
                indegree[t] = indegree.get(t, 0) + 1
        roots = sorted(s for s, c in indegree.items() if c == 0)
        return roots[0] if roots else sorted(ctx.stage_graph.transitions)[0]

    def _select_next_stage(self, candidates: set[str]) -> str:
        """Select next stage from multiple candidates via route_engine or lexical sort."""
        ctx = self._ctx
        if hasattr(ctx.route_engine, "select_stage") and callable(ctx.route_engine.select_stage):
            try:
                return ctx.route_engine.select_stage(
                    candidates=sorted(candidates),
                    run_id=ctx.run_id,
                    completed_stages=list(ctx.stage_summaries.keys()),
                )
            except Exception as exc:
                ctx.log_best_effort_fn(
                    logging.DEBUG,
                    "stage_orchestrator.select_next_stage_failed",
                    exc,
                    run_id=ctx.run_id,
                )
        return sorted(candidates)[0]

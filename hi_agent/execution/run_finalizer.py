"""Run finalization extracted from RunExecutor (HI-W7-004)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts.requests import RunResult

_logger = logging.getLogger(__name__)


@dataclass
class RunFinalizerContext:
    """State and callbacks required to finalize a run."""

    run_id: str
    contract: Any
    lifecycle: Any
    kernel: Any
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    current_stage: Any = None
    dag: Any = None
    action_seq: Any = None
    policy_versions: Any = None
    raw_memory: Any = None
    mid_term_store: Any = None
    long_term_consolidator: Any = None
    failure_collector: Any = None
    feedback_store: Any = None
    restart_policy: Any = None
    last_exception_msg: str | None = None
    last_exception_type: str | None = None
    skill_ids_used: list[str] = field(default_factory=list)
    run_start_monotonic: float | None = None
    capability_provenance_store: dict[str, list[dict]] = field(default_factory=dict)
    pending_subrun_futures: dict[str, Any] = field(default_factory=dict)
    completed_subrun_results: dict[str, Any] = field(default_factory=dict)
    emit_observability_fn: Callable[..., Any] | None = None
    persist_snapshot_fn: Callable[..., Any] | None = None
    finalize_skill_outcomes_fn: Callable[..., Any] | None = None
    sync_to_context_fn: Callable[..., Any] | None = None
    env: str = "dev"
    readiness_snapshot: dict[str, Any] = field(default_factory=dict)
    mcp_status: dict[str, Any] = field(default_factory=dict)
    stages: list[Any] = field(default_factory=list)


class RunFinalizer:
    """Finalize run execution state into a RunResult."""

    def __init__(
        self,
        ctx: RunFinalizerContext,
        team_space: Any | None = None,
        share_to_team: bool = False,
    ) -> None:
        self.ctx = ctx
        self._team_space = team_space
        self._share_to_team = share_to_team

    def _cancel_pending_subruns(self, status: str) -> None:
        """Cancel any sub-run futures and reflection tasks not collected before finalization."""
        ctx = self.ctx
        # J8-1: Cancel orphaned reflection background tasks.
        for task in list(getattr(ctx, "_pending_reflection_tasks", [])):
            try:
                if callable(getattr(task, "done", None)) and not task.done():
                    task.cancel()
                    _logger.warning(
                        "runner.reflect_task_cancelled_at_finalization run_id=%s",
                        ctx.run_id,
                    )
            except Exception as _exc:
                _logger.debug("runner.reflect_task_cancel_failed error=%s", _exc)
        _pending_reflect = getattr(ctx, "_pending_reflection_tasks", [])
        _pending_reflect.clear()

        pending = ctx.pending_subrun_futures
        for task_id, future in list(pending.items()):
            try:
                if callable(getattr(future, "done", None)) and not future.done():
                    future.cancel()
                    _logger.warning(
                        "runner.subrun_cancelled_at_finalization "
                        "task_id=%s run_status=%s run_id=%s",
                        task_id,
                        status,
                        ctx.run_id,
                    )
            except Exception as _exc:
                _logger.warning("runner.subrun_cancel_failed task_id=%s error=%s", task_id, _exc)
        pending.clear()
        completed = ctx.completed_subrun_results
        if completed:
            _logger.debug(
                "runner.subrun_uncollected_results_cleared count=%d run_id=%s",
                len(completed),
                ctx.run_id,
            )
            completed.clear()

    def _collect_stage_type_summaries(self) -> list[dict]:
        """Collect per-stage type info with StageProvenance.

        llm_mode is derived from capability_provenance_store entries:
        - Entries present (from heuristic path): llm_mode="heuristic", fallback_used=True
        - No entries: llm_mode="unknown", fallback_used=False
          (real LLM results do not inject _provenance; absence is ambiguous)
        capability_mode is derived from recorded invocation mode values.
        """
        from hi_agent.contracts.execution_provenance import StageProvenance

        ctx = self.ctx
        stages = ctx.stages or list(ctx.stage_summaries.keys())
        summaries = []
        for stage in stages:
            stage_id = (
                getattr(stage, "stage_id", None)
                or getattr(stage, "name", None)
                or (stage if isinstance(stage, str) else "unknown")
            )
            cap_prov_list = ctx.capability_provenance_store.get(str(stage_id), [])
            if cap_prov_list:
                # Provenance entries are only injected by the heuristic fallback path.
                # If any entry exists the stage used heuristic routing.
                llm_mode = "heuristic"
                fallback_used = True
                fallback_reasons = ["heuristic_routing"]
                modes = [r.get("mode", "sample") for r in cap_prov_list if isinstance(r, dict)]
                if all(m == "mcp" for m in modes):
                    capability_mode = "mcp"
                elif all(m == "external" for m in modes):
                    capability_mode = "external"
                elif all(m == "profile" for m in modes):
                    capability_mode = "profile"
                elif all(m == "sample" for m in modes):
                    capability_mode = "sample"
                else:
                    capability_mode = "unknown"
            else:
                # No provenance entries: either real LLM was used (no _provenance key)
                # or no capability was invoked. Cannot assert "heuristic" here.
                llm_mode = "unknown"
                fallback_used = False
                fallback_reasons = []
                capability_mode = "unknown"
            prov = StageProvenance(
                stage_id=str(stage_id),
                llm_mode=llm_mode,
                capability_mode=capability_mode,
                fallback_used=fallback_used,
                fallback_reasons=fallback_reasons,
                duration_ms=getattr(stage, "duration_ms", 0) or 0,
            )
            summaries.append(
                {
                    "stage_id": str(stage_id),
                    "type": llm_mode,
                    "provenance": prov,
                }
            )
        return summaries

    def _get_mcp_transport_status(self) -> str:
        """Return MCP transport status string for provenance.

        Reads mcp_status dict if available; defaults to "not_wired" per
        CLAUDE.md transport_status convention.
        """
        return self.ctx.mcp_status.get("transport_status", "not_wired")

    def finalize(self, outcome: str) -> RunResult:
        """Run post-execution finalization for a given outcome.

        Handles observability, evolve engine, skill outcomes, episode
        building, cost summary, short-term memory, and knowledge ingestion.

        Returns:
            A structured :class:`~hi_agent.contracts.requests.RunResult`
            containing run_id, status, per-stage summaries, and artifact IDs.
            ``str(result)`` returns the status string for backward compatibility.
        """
        ctx = self.ctx
        self._cancel_pending_subruns(outcome)

        # Flush and close L0 JSONL before L0Summarizer reads it.
        if getattr(ctx, "raw_memory", None) is not None:
            try:
                ctx.raw_memory.close()
            except Exception as _exc:
                _logger.warning("runner.raw_memory_close_failed error=%s", _exc)

        ctx.lifecycle.finalize_run(
            outcome,
            run_id=ctx.run_id,
            current_stage=ctx.current_stage,
            contract=ctx.contract,
            stage_summaries=ctx.stage_summaries,
            dag=ctx.dag,
            action_seq=ctx.action_seq,
            policy_versions=ctx.policy_versions,
            kernel=ctx.kernel,
            skill_ids_used=ctx.skill_ids_used,
            emit_observability_fn=ctx.emit_observability_fn,
            persist_snapshot_fn=ctx.persist_snapshot_fn,
            finalize_skill_outcomes_fn=ctx.finalize_skill_outcomes_fn,
            sync_to_context_fn=ctx.sync_to_context_fn,
        )
        # Build structured result from accumulated stage summaries.
        stage_dicts: list[dict] = []
        all_artifact_ids: list[str] = []
        for stage_id, summary in ctx.stage_summaries.items():
            stage_dicts.append(
                {
                    "stage_id": stage_id,
                    "stage_name": getattr(summary, "stage_name", stage_id),
                    "outcome": getattr(summary, "outcome", "unknown"),
                    "findings": list(getattr(summary, "findings", [])),
                    "decisions": list(getattr(summary, "decisions", [])),
                    "artifact_ids": list(getattr(summary, "artifact_ids", [])),
                }
            )
            all_artifact_ids.extend(getattr(summary, "artifact_ids", []))

        # --- Failure attribution ---
        failed_stage_id: str | None = None
        error_detail: str | None = None
        failure_code: str | None = None
        is_retryable: bool = False

        if outcome != "completed":
            failed_stage_id = ctx.current_stage
            # Prefer exception message captured during execute()
            exc_msg = ctx.last_exception_msg
            if exc_msg:
                error_detail = exc_msg
            else:
                # Fall back to the failed stage's outcome info
                summary = ctx.stage_summaries.get(failed_stage_id or "")
                if summary is not None:
                    stage_outcome = getattr(summary, "outcome", "")
                    if stage_outcome and stage_outcome != "succeeded":
                        error_detail = f"Stage {failed_stage_id!r} outcome: {stage_outcome}"
            if not error_detail:
                error_detail = f"Run failed at stage {failed_stage_id!r}"
            # Precise failure attribution: query FailureCollector for structured record.
            # Map raw outcome strings to proper FailureCode enum values.
            outcome_to_failure_code = {
                "failed": "no_progress",
                "aborted": "exploration_budget_exhausted",
                "timeout": "callback_timeout",
                "unsafe": "unsafe_action_blocked",
            }
            failure_code = outcome_to_failure_code.get(outcome, outcome)
            is_retryable = False
            collector = ctx.failure_collector
            if collector is not None:
                try:
                    from hi_agent.failures.taxonomy import FAILURE_RECOVERY_MAP

                    unresolved = collector.get_unresolved()
                    last_failure = unresolved[-1] if unresolved else None
                    if last_failure is None:
                        all_records = collector.get_all()
                        last_failure = all_records[-1] if all_records else None
                    if last_failure is not None:
                        # Use real FailureCode instead of bare outcome string
                        fc = last_failure.failure_code
                        failure_code = fc.value if hasattr(fc, "value") else str(fc)
                        # Enrich error_detail with FailureRecord message
                        if last_failure.message:
                            error_detail = last_failure.message
                        # Enrich failed_stage_id from FailureRecord
                        if last_failure.stage_id:
                            failed_stage_id = last_failure.stage_id
                        # Determine retryability from FAILURE_RECOVERY_MAP
                        recovery = FAILURE_RECOVERY_MAP.get(fc, "")
                        is_retryable = recovery in (
                            "retry_or_downgrade_model",
                            "recovery_path",
                            "task_view_degradation",
                            "watchdog_handling",
                        )
                except Exception as _attr_exc:
                    _logger.debug("Failure attribution enrichment failed: %s", _attr_exc)
            # Final fallback: retryable if a restart policy engine is wired
            if not is_retryable:
                is_retryable = ctx.restart_policy is not None

        # Cross-validate stage summaries against final outcome.
        # The failed stage cannot show "succeeded" or "active" — the compressor
        # may mark it "succeeded" if any branch completed, or "active" if the
        # stage was interrupted before an explicit completion event was recorded.
        if outcome != "completed" and failed_stage_id is not None:
            for sd in stage_dicts:
                if sd["stage_id"] == failed_stage_id and sd.get("outcome") in (
                    "succeeded",
                    "active",
                    "unknown",
                ):
                    sd["outcome"] = "failed"

        # --- Acceptance criteria evaluation ---
        # If outcome is "completed", verify declared acceptance_criteria.
        # Supported formats:
        #   "required_stage:<stage_id>"  — stage must have outcome "succeeded"
        #   "required_artifact:<artifact_id>" — artifact_id must be present
        # Any failing criterion downgrades outcome to "failed".
        if outcome == "completed":
            criteria = getattr(ctx.contract, "acceptance_criteria", None) or []
            criteria_failures: list[str] = []
            completed_stage_ids = {
                sd["stage_id"] for sd in stage_dicts if sd.get("outcome") == "succeeded"
            }
            for criterion in criteria:
                if not isinstance(criterion, str):
                    continue
                if criterion.startswith("required_stage:"):
                    required_sid = criterion[len("required_stage:") :]
                    if required_sid not in completed_stage_ids:
                        criteria_failures.append(criterion)
                elif criterion.startswith("required_artifact:"):
                    required_aid = criterion[len("required_artifact:") :]
                    if required_aid not in all_artifact_ids:
                        criteria_failures.append(criterion)
            if criteria_failures:
                outcome = "failed"
                failure_code = "invalid_context"
                error_detail = f"Acceptance criteria not met: {criteria_failures}"
                _logger.warning(
                    "runner.acceptance_criteria_failed run_id=%s criteria=%s",
                    ctx.run_id,
                    criteria_failures,
                )

        # --- Exception-type → failure_code improvement (P2-NEW-03) ---
        # When outcome is failed and failure_code is still the naive default,
        # use the captured exception type for more precise attribution.
        if outcome != "completed" and failure_code == "no_progress":
            exc_type = ctx.last_exception_type
            if exc_type:
                exc_type_to_failure_code: dict[str, str] = {
                    "TimeoutError": "callback_timeout",
                    "asyncio.TimeoutError": "callback_timeout",
                    "concurrent.futures.TimeoutError": "callback_timeout",
                    "MemoryError": "execution_budget_exhausted",
                    "RecursionError": "execution_budget_exhausted",
                    "PermissionError": "harness_denied",
                    "KeyError": "invalid_context",
                    "ValueError": "invalid_context",
                    "TypeError": "invalid_context",
                }
                mapped = exc_type_to_failure_code.get(exc_type)
                if mapped:
                    failure_code = mapped

        # --- L0 -> L2 consolidation ---
        try:
            from pathlib import Path as _Path

            _raw_run_id = getattr(ctx.raw_memory, "_run_id", "")
            _raw_file = getattr(ctx.raw_memory, "_file", None)
            # Attempt to derive base_dir from the log path stored on the store
            _raw_base = getattr(ctx.raw_memory, "_base_dir", None)
            if _raw_base is None and _raw_run_id:
                # Fallback: check if RawMemoryStore exposed _base_dir_path
                _raw_base = getattr(ctx.raw_memory, "_base_dir_path", None)
            if _raw_base is not None:
                from hi_agent.memory.l0_summarizer import L0Summarizer

                _summary = L0Summarizer().summarize_run(ctx.run_id, _Path(_raw_base))
                if _summary is not None and ctx.mid_term_store is not None:
                    ctx.mid_term_store.save(_summary)
        except Exception as _cons_exc:  # consolidation must never crash the run
            _logger.debug("L0->L2 consolidation failed: %s", _cons_exc)

        # --- L2 -> L3 consolidation ---
        _consolidator = ctx.long_term_consolidator
        if _consolidator is not None:
            try:
                _consolidator.consolidate(days=1)
            except Exception as _exc:
                _logger.debug("L2->L3 consolidation failed: %s", _exc)

        # --- FeedbackStore: submit neutral record for completed run ---
        if ctx.feedback_store is not None:
            from hi_agent.evolve.feedback_store import RunFeedback

            try:
                ctx.feedback_store.submit(RunFeedback(run_id=ctx.run_id, rating=0.5))
                _logger.debug("feedback_store: neutral record submitted for run %s", ctx.run_id)
            except Exception as _fb_exc:
                _logger.warning("feedback_store: submit failed: %s", _fb_exc)

        # --- Wall-clock duration ---
        _start = ctx.run_start_monotonic
        duration_ms = int((time.monotonic() - _start) * 1000) if _start is not None else 0

        run_result = RunResult(
            run_id=ctx.run_id,
            status=outcome,
            stages=stage_dicts,
            artifacts=all_artifact_ids,
            error=error_detail,
            failure_code=failure_code,
            failed_stage_id=failed_stage_id,
            is_retryable=is_retryable,
            duration_ms=duration_ms,
        )

        # --- Execution provenance (HI-W1-D3-001) ---
        # Populate after RunResult construction so all fields are finalized.
        try:
            from hi_agent.contracts.execution_provenance import ExecutionProvenance
            from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode

            _stage_summaries = self._collect_stage_type_summaries()
            _prov = ExecutionProvenance.build_from_stages(
                stage_summaries=_stage_summaries,
                runtime_context={
                    "runtime_mode": resolve_runtime_mode(
                        env=ctx.env,
                        readiness=ctx.readiness_snapshot,
                    ),
                    "mcp_transport": self._get_mcp_transport_status(),
                    "kernel_mode": getattr(ctx.kernel, "mode", "unknown"),
                },
            )
            run_result.execution_provenance = _prov
        except Exception as _prov_exc:  # provenance must never crash the run
            _logger.warning("runner.provenance_build_failed error=%s", _prov_exc)

        # --- Opt-in team sync ---
        if self._share_to_team and self._team_space is not None:
            try:
                self._team_space.publish(
                    event_type="run_summary",
                    payload={"outcome": outcome},
                    source_run_id=ctx.run_id,
                    source_user_id="",
                    source_session_id="",
                    publish_reason="auto_sync",
                )
            except Exception as _sync_exc:
                _logger.warning("runner.team_sync_failed error=%s", _sync_exc)

        return run_result

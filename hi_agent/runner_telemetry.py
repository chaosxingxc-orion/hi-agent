"""Telemetry and observability delegation extracted from RunExecutor.

This module contains the RunTelemetry helper class which encapsulates
event recording, metrics collection, skill observation, and
observability hook dispatch.  RunExecutor delegates to an instance
of this class rather than implementing the logic inline.
"""

from __future__ import annotations

import logging
import time as _time_module
from collections.abc import Callable
from datetime import UTC
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)
from hi_agent.events import EventEmitter
from hi_agent.memory import RawEventRecord, RawMemoryStore
from hi_agent.observability.trace_context import TraceContextManager

if TYPE_CHECKING:
    from hi_agent.observability.tracing import Tracer
    from hi_agent.skill.recorder import SkillUsageRecorder


class RunTelemetry:
    """Encapsulates telemetry, event recording, and skill observation."""

    def __init__(
        self,
        *,
        event_emitter: EventEmitter,
        raw_memory: RawMemoryStore,
        observability_hook: Callable[[str, dict[str, object]], None] | None,
        metrics_collector: Any | None,
        skill_observer: Any | None,
        skill_recorder: SkillUsageRecorder | None,
        session: Any | None,
        context_manager: Any | None,
        tracer: Tracer | None = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.raw_memory = raw_memory
        self.observability_hook = observability_hook
        self.metrics_collector = metrics_collector
        self.skill_observer = skill_observer
        self.skill_recorder = skill_recorder
        self.session = session
        self.context_manager = context_manager
        self.trace_ctx_manager = TraceContextManager()
        self.tracer: Tracer | None = tracer
        self._run_start_time: float = _time_module.monotonic()

    # ------------------------------------------------------------------
    # Core event / observability
    # ------------------------------------------------------------------

    def emit_observability(self, name: str, payload: dict[str, object]) -> None:
        """Emit one observability callback event without impacting run success."""
        if self.metrics_collector is not None:
            try:
                self.record_metric(name, payload)
            except Exception as exc:
                logger.warning(
                    "Metrics collection for event %r failed: %s",
                    name,
                    exc,
                    extra={"run_id": payload.get("run_id")},
                )

        if self.observability_hook is None:
            return
        try:
            self.observability_hook(name, payload)
        except Exception as exc:
            logger.warning(
                "Observability hook for event %r failed: %s",
                name,
                exc,
                extra={"run_id": payload.get("run_id")},
            )
            return

    def record_metric(self, name: str, payload: dict[str, object]) -> None:
        """Translate observability events to structured metric recordings."""
        mc = self.metrics_collector
        if mc is None:
            return
        # Build base labels, including trace_id when available.
        trace_ctx = self.trace_ctx_manager.current()
        trace_label: dict[str, str] = {}
        if trace_ctx is not None:
            trace_label = {"trace_id": trace_ctx.trace_id}
        if name == "run_completed":
            mc.record("runs_total", 1.0, {"status": "completed", **trace_label})
            mc.increment("runs_active", -1.0)
            self._export_run_span(name="run", error=None, trace_ctx=trace_ctx)
        elif name == "run_failed":
            mc.record("runs_total", 1.0, {"status": "failed", **trace_label})
            mc.increment("runs_active", -1.0)
            error_msg = str(payload.get("error", "unknown"))
            self._export_run_span(name="run", error=error_msg, trace_ctx=trace_ctx)
        elif name == "run_cost_summary":
            # Record cumulative cost counter and per-run histogram.
            total_usd = float(payload.get("total_cost_usd", 0.0))
            if total_usd > 0:
                mc.record("llm_cost_usd_total", total_usd, trace_label or None)
                mc.record("llm_cost_per_run", total_usd, trace_label or None)

    def _export_run_span(
        self,
        name: str,
        error: str | None,
        trace_ctx: Any | None,
    ) -> None:
        """Export a run-level span record via the configured tracer exporters."""
        if self.tracer is None:
            return
        try:
            import time as _t

            from hi_agent.observability.tracing import SpanRecord

            end_time = _t.monotonic()
            duration_ms = (end_time - self._run_start_time) * 1000.0
            now_wall = _t.time()
            start_wall = now_wall - (duration_ms / 1000.0)
            trace_id = trace_ctx.trace_id if trace_ctx is not None else name
            span_id = trace_ctx.span_id if trace_ctx is not None else name
            record = SpanRecord(
                name=name,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                start_time=start_wall,
                end_time=now_wall,
                duration_ms=duration_ms,
                error=error,
            )
            for exporter in self.tracer._exporters:
                try:
                    exporter.export(record)
                except Exception as exc:
                    # TODO: add run_id context — not accessible in _export_run_span
                    logger.warning("TraceExporter.export failed: %s", exc)
        except Exception as exc:
            # TODO: add run_id context — not accessible in _export_run_span
            logger.warning("_export_run_span failed: %s", exc)

    def record_event(
        self,
        event_type: str,
        payload: dict,
        *,
        run_id: str,
        current_stage: str,
    ) -> None:
        """Record event to both emitter and raw memory store."""
        # Inject trace context into emitted events.
        trace_ctx = self.trace_ctx_manager.current()
        trace_kwargs: dict[str, str] = {}
        if trace_ctx is not None:
            trace_kwargs = {
                "trace_id": trace_ctx.trace_id,
                "span_id": trace_ctx.span_id,
                "parent_span_id": trace_ctx.parent_span_id,
            }
        self.event_emitter.emit(
            event_type=event_type,
            run_id=run_id,
            payload=payload,
            **trace_kwargs,
        )
        self.raw_memory.append(RawEventRecord(event_type=event_type, payload=payload))
        # Delegate to session (additive -- never break core execution)
        if self.session is not None:
            try:
                self.session.append_record(event_type, payload, stage_id=current_stage)
                self.session.emit_event(event_type, payload)
            except Exception as exc:
                logger.warning(
                    "Session record/emit for event %r failed: %s",
                    event_type,
                    exc,
                    extra={"run_id": run_id, "stage_id": current_stage},
                )
        # ContextManager: add history entry for context window tracking
        if self.context_manager is not None:
            try:
                import json as _json_mod

                self.context_manager.add_history_entry(
                    role="system",
                    content=f"[{event_type}] {_json_mod.dumps(payload, default=str)[:500]}",
                    metadata={"stage_id": current_stage},
                )
            except Exception as exc:
                logger.warning(
                    "ContextManager history entry for event %r failed: %s",
                    event_type,
                    exc,
                    extra={"run_id": run_id, "stage_id": current_stage},
                )

    # ------------------------------------------------------------------
    # Skill telemetry
    # ------------------------------------------------------------------

    def record_skill_usage_from_proposal(
        self, proposal: object, stage_id: str, *, run_id: str, skill_ids_used: list[str]
    ) -> None:
        """If proposal has skill_id metadata, record skill usage (best-effort)."""
        if self.skill_recorder is None:
            return
        try:
            skill_id = getattr(proposal, "skill_id", None)
            if skill_id:
                self.skill_recorder.record_usage(skill_id=skill_id, run_id=run_id, success=True)
                if skill_id not in skill_ids_used:
                    skill_ids_used.append(skill_id)
        except Exception as exc:
            logger.warning(
                "Skill usage recording from proposal failed: %s",
                exc,
                extra={"run_id": run_id, "stage_id": stage_id},
            )

    def finalize_skill_outcomes(
        self, outcome: str, *, run_id: str, skill_ids_used: list[str]
    ) -> None:
        """After run completes, record final outcome per skill used (best-effort)."""
        if self.skill_recorder is None or not skill_ids_used:
            return
        try:
            success = outcome == "completed"
            for skill_id in skill_ids_used:
                self.skill_recorder.record_usage(skill_id=skill_id, run_id=run_id, success=success)
        except Exception as exc:
            logger.warning(
                "Finalizing skill outcomes for run %r failed: %s",
                run_id,
                exc,
                extra={"run_id": run_id},
            )

    def observe_skill_execution(
        self,
        proposal: object,
        stage_id: str,
        action_succeeded: bool,
        payload: dict,
        result: dict | None,
        *,
        run_id: str,
        action_seq: int,
        task_family: str,
    ) -> None:
        """Record skill execution observation (best-effort, non-blocking)."""
        if self.skill_observer is None:
            return
        try:
            from datetime import datetime

            from hi_agent.skill.observer import SkillObservation

            skill_id = getattr(proposal, "skill_id", "") or getattr(
                proposal,
                "action_kind",
                "unknown",
            )
            skill_version = getattr(proposal, "version", "0.1.0")
            quality_score = None
            tokens_used = 0
            if isinstance(result, dict):
                quality_score = result.get("score")
                if quality_score is not None:
                    try:
                        quality_score = float(quality_score)
                    except (ValueError, TypeError):
                        quality_score = None
                tokens_used = int(result.get("tokens_used", 0))

            obs = SkillObservation(
                observation_id=f"{run_id}:{stage_id}:{action_seq}",
                skill_id=skill_id,
                skill_version=skill_version,
                run_id=run_id,
                stage_id=stage_id,
                timestamp=datetime.now(UTC).isoformat(),
                success=action_succeeded,
                input_summary=str(payload)[:500],
                output_summary=str(result)[:500] if result else "",
                quality_score=quality_score,
                tokens_used=tokens_used,
                task_family=task_family,
            )
            self.skill_observer.observe(obs)
        except Exception as exc:
            logger.warning(
                "Skill execution observation for stage %r failed: %s",
                stage_id,
                exc,
                extra={"run_id": run_id, "stage_id": stage_id},
            )

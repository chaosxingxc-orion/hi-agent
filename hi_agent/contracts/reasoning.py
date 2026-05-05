"""Reasoning trace storage contract — allows business layer to persist structured reasoning.

Business-layer stage handlers call
``StageExecutor.append_reasoning_step(run_id, stage_id, step)`` (or access the
live ``ReasoningTrace`` via ``StageExecutor.get_reasoning_trace(...)``) during
stage execution.  The platform persists the trace to L1 short-term memory when
the stage finalizes, keyed by ``(run_id, stage_id)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


# scope: process-internal — step value object; parent ReasoningTrace carries spine
@dataclass
class ReasoningStep:
    """A single step in a structured reasoning trace.

    Business-layer stage handlers populate these; the platform stores them.
    ``step_index`` is monotonically increasing within a trace (assigned by
    ``ReasoningTrace.append`` when left at the default ``-1``).
    """

    description: str = ""
    step_index: int = -1
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    ts: str = field(default_factory=_now_iso)

    # --- Back-compat fields kept for pre-existing producers ---
    step_id: str = ""
    stage_id: str = ""
    action: str = ""
    thought: str = ""
    timestamp: str = ""


class SpineCompletenessError(ValueError):
    """Raised when a spine-bearing dataclass is constructed with an empty required field.

    W34-F.3 (B-W34-2): Rule 12 spine fields (``tenant_id``, ``run_id``,
    ``stage_id`` for ReasoningTrace) must be populated under research/prod
    posture. A bare ``ValueError`` would suffice but a typed subclass lets
    upstream gates assert the failure mode without string-matching.
    """


@dataclass
class ReasoningTrace:
    """A collection of reasoning steps for a single stage execution."""

    run_id: str
    stage_id: str
    tenant_id: str = ""  # Rule 12 spine — validated under research/prod posture
    trace_id: str = ""
    steps: list[ReasoningStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        """W34-F.3 (B-W34-2): validate Rule 12 spine completeness at construction.

        Under research/prod posture every ReasoningTrace MUST carry a
        non-empty ``tenant_id``, ``run_id``, and ``stage_id``. Under dev
        posture the constraints are relaxed to a warning so local tooling
        and the default-offline test profile keep working.

        The check is posture-aware (Rule 11): missing fields are a hard
        failure under research/prod and a logged warning under dev. This
        prevents the silent-empty-spine pattern flagged in W33's outstanding
        items while preserving developer ergonomics.
        """
        # Imported lazily to avoid a hot-path import cycle during module
        # initialisation; ``Posture.from_env`` is cheap.
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        missing: list[str] = []
        if not self.run_id:
            missing.append("run_id")
        if not self.stage_id:
            missing.append("stage_id")
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if posture.is_strict:
            raise SpineCompletenessError(
                "ReasoningTrace constructed without required spine fields "
                f"under posture={posture.value}: missing={missing}. "
                "Populate the fields at the construction site (Rule 12)."
            )
        # Dev posture: emit a warning so the gap is visible without breaking
        # local development. The W34 backfill test asserts no production
        # construction site reaches this branch under realistic input.
        import logging
        logging.getLogger("hi_agent.contracts.reasoning").warning(
            "reasoning_trace_spine_incomplete: missing=%s posture=%s; "  # wave-literal-ok
            "would fail-closed under research/prod. (W34-F.3)",  # wave-literal-ok
            missing,
            posture.value,
        )

    def append(self, step: ReasoningStep) -> None:
        """Append a step, assigning ``step_index`` if unset."""
        if step.step_index is None or step.step_index < 0:
            step.step_index = len(self.steps)
        self.steps.append(step)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "tenant_id": self.tenant_id,
            "trace_id": self.trace_id,
            "steps": [
                {
                    "description": s.description,
                    "step_index": s.step_index,
                    "evidence_refs": list(s.evidence_refs),
                    "confidence": s.confidence,
                    "ts": s.ts,
                    "step_id": s.step_id,
                    "stage_id": s.stage_id,
                    "action": s.action,
                    "thought": s.thought,
                    "timestamp": s.timestamp,
                }
                for s in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReasoningTrace:
        """Deserialize a ReasoningTrace from a dict.

        W34-F.3: ``__post_init__`` runs as part of construction. Under
        research/prod posture the deserialiser will raise
        ``SpineCompletenessError`` if the persisted dict lacks any required
        spine field — which is the desired behaviour: stale or corrupt
        records should fail closed rather than re-enter the system.
        """
        steps = [
            ReasoningStep(
                description=s.get("description", ""),
                step_index=s.get("step_index", -1),
                evidence_refs=list(s.get("evidence_refs", [])),
                confidence=s.get("confidence"),
                ts=s.get("ts", ""),
                step_id=s.get("step_id", ""),
                stage_id=s.get("stage_id", ""),
                action=s.get("action", ""),
                thought=s.get("thought", ""),
                timestamp=s.get("timestamp", ""),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            run_id=data.get("run_id", ""),
            stage_id=data.get("stage_id", ""),
            tenant_id=data.get("tenant_id", ""),
            trace_id=data.get("trace_id", ""),
            steps=steps,
        )

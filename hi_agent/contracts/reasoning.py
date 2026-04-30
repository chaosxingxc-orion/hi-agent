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


@dataclass
class ReasoningTrace:
    """A collection of reasoning steps for a single stage execution."""

    run_id: str
    stage_id: str
    tenant_id: str  # Rule 12 spine — required; no default
    trace_id: str = ""
    steps: list[ReasoningStep] = field(default_factory=list)

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
        """Deserialize a ReasoningTrace from a dict."""
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
            trace_id=data.get("trace_id", ""),
            steps=steps,
        )

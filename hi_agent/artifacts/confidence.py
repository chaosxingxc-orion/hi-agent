"""Pluggable confidence scoring for artifacts.

Platform provides the protocol and a naive baseline implementation.
Business agents subclass ``ConfidenceScorer`` with domain-specific logic
(e.g. cross-source agreement, citation quality) and register their scorer
via ``TraceConfig`` / ``SystemBuilder``. When a scorer is configured,
``finalize_artifact()`` populates ``Artifact.confidence``. When no scorer
is configured, ``confidence`` keeps its caller-assigned value.

This file is business-neutral: it does NOT encode any domain heuristic
beyond the trivially mechanical default (evidence_count / 10).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.artifacts.contracts import Artifact


# scope: process-internal — pure value object (CLAUDE.md Rule 12 carve-out)
@dataclass
class ConfidenceInputs:
    """Generic signals available when scoring an artifact's confidence.

    Business layers may ignore fields they don't care about. Platform code
    populates what it can observe from the artifact and its provenance.
    """

    evidence_count: int = 0
    sources: list[str] = field(default_factory=list)
    consistency_score: float | None = None
    producer_action_id: str = ""
    artifact_type: str = ""


class ConfidenceScorer(ABC):
    """Business layer implements this; platform calls it at artifact finalization."""

    @abstractmethod
    def score(self, inputs: ConfidenceInputs) -> float:
        """Return confidence in [0.0, 1.0]."""


class DefaultConfidenceScorer(ConfidenceScorer):
    """Baseline scorer: confidence grows linearly with evidence count, caps at 1.0.

    Exists so platform tests have a deterministic reference implementation.
    Business layers should subclass ``ConfidenceScorer`` with real logic.
    """

    def score(self, inputs: ConfidenceInputs) -> float:
        """Return ``min(1.0, evidence_count / 10.0)``."""
        return min(1.0, max(0.0, inputs.evidence_count / 10.0))


def finalize_artifact(
    artifact: Artifact,
    scorer: ConfidenceScorer | None,
    *,
    evidence_count: int | None = None,
    consistency_score: float | None = None,
) -> Artifact:
    """Populate ``artifact.confidence`` from ``scorer`` if configured.

    ``evidence_count`` defaults to ``len(artifact.source_refs)``. Callers may
    override when the artifact's evidence is tracked elsewhere (e.g. upstream
    artifacts). Returns the same artifact for chaining.
    """
    if scorer is None:
        return artifact
    inputs = ConfidenceInputs(
        evidence_count=evidence_count if evidence_count is not None else len(artifact.source_refs),
        sources=list(artifact.source_refs),
        consistency_score=consistency_score,
        producer_action_id=artifact.producer_action_id,
        artifact_type=artifact.artifact_type,
    )
    artifact.confidence = scorer.score(inputs)
    return artifact


__all__ = [
    "ConfidenceInputs",
    "ConfidenceScorer",
    "DefaultConfidenceScorer",
    "finalize_artifact",
]

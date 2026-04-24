"""Neutral platform artifact contracts and registry."""

from hi_agent.artifacts.confidence import (
    ConfidenceInputs,
    ConfidenceScorer,
    DefaultConfidenceScorer,
    finalize_artifact,
)
from hi_agent.artifacts.contracts import (
    Artifact,
    DocumentArtifact,
    EvaluationArtifact,
    EvidenceArtifact,
    ResourceArtifact,
    StructuredDataArtifact,
)
from hi_agent.artifacts.registry import ArtifactRegistry

__all__ = [
    "Artifact",
    "ArtifactRegistry",
    "ConfidenceInputs",
    "ConfidenceScorer",
    "DefaultConfidenceScorer",
    "DocumentArtifact",
    "EvaluationArtifact",
    "EvidenceArtifact",
    "ResourceArtifact",
    "StructuredDataArtifact",
    "finalize_artifact",
]

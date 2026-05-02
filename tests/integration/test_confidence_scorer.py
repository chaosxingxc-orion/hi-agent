"""Tests for pluggable ConfidenceScorer (P-5).

Platform provides the base class and a baseline scorer. Business layers
subclass and register via TraceConfig. These tests verify the base class
contract, the baseline's deterministic behaviour, subclass overriding,
and the wiring path through ``finalize_artifact()``.
"""

from __future__ import annotations

import pytest
from hi_agent.artifacts import (
    Artifact,
    ConfidenceInputs,
    ConfidenceScorer,
    DefaultConfidenceScorer,
    EvidenceArtifact,
    finalize_artifact,
)


class TestDefaultConfidenceScorer:
    def test_default_scorer_baseline(self):
        scorer = DefaultConfidenceScorer()
        assert scorer.score(ConfidenceInputs(evidence_count=0)) == 0.0
        assert scorer.score(ConfidenceInputs(evidence_count=5)) == 0.5
        assert scorer.score(ConfidenceInputs(evidence_count=10)) == 1.0
        # Cap at 1.0
        assert scorer.score(ConfidenceInputs(evidence_count=999)) == 1.0

    def test_default_scorer_clamps_negative_evidence_to_zero(self):
        scorer = DefaultConfidenceScorer()
        assert scorer.score(ConfidenceInputs(evidence_count=-3)) == 0.0


class TestSubclassOverride:
    def test_subclass_override(self):
        """Business layer can subclass and plug in their own logic."""

        class AlwaysHighScorer(ConfidenceScorer):
            def score(self, inputs: ConfidenceInputs) -> float:
                return 0.95

        scorer = AlwaysHighScorer()
        assert scorer.score(ConfidenceInputs(evidence_count=0)) == 0.95

    def test_subclass_can_inspect_all_inputs(self):
        """Verify that custom scorers see source list, consistency, and type."""
        seen: dict = {}

        class InspectingScorer(ConfidenceScorer):
            def score(self, inputs: ConfidenceInputs) -> float:
                seen["sources"] = list(inputs.sources)
                seen["consistency"] = inputs.consistency_score
                seen["artifact_type"] = inputs.artifact_type
                return 0.42

        scorer = InspectingScorer()
        out = scorer.score(
            ConfidenceInputs(
                evidence_count=2,
                sources=["http://a", "http://b"],
                consistency_score=0.7,
                artifact_type="evidence",
            )
        )
        assert out == 0.42
        assert seen["sources"] == ["http://a", "http://b"]
        assert seen["consistency"] == 0.7
        assert seen["artifact_type"] == "evidence"

    def test_abstract_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            ConfidenceScorer()  # type: ignore[abstract]  expiry_wave: permanent


class TestFinalizeArtifact:
    def test_artifact_gets_confidence_when_scorer_configured(self):
        artifact = EvidenceArtifact(claim="x", source_refs=["s1", "s2", "s3"])
        # confidence starts at dataclass default
        assert artifact.confidence == 0.0

        finalize_artifact(artifact, DefaultConfidenceScorer())

        # 3 sources -> evidence_count=3 -> 0.3
        assert artifact.confidence == pytest.approx(0.3)

    def test_artifact_confidence_unchanged_when_no_scorer(self):
        """No scorer configured -> confidence stays at caller-assigned value."""
        artifact = Artifact(confidence=0.42)
        finalize_artifact(artifact, None)
        assert artifact.confidence == 0.42

    def test_explicit_evidence_count_overrides_source_refs(self):
        artifact = EvidenceArtifact(claim="x", source_refs=["s1"])
        finalize_artifact(artifact, DefaultConfidenceScorer(), evidence_count=7)
        assert artifact.confidence == pytest.approx(0.7)

    def test_finalize_returns_same_artifact(self):
        """Returned object is identity-equal for chaining."""
        artifact = Artifact()
        result = finalize_artifact(artifact, DefaultConfidenceScorer())
        assert result is artifact

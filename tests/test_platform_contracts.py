"""Unit tests for P-1 (Provenance) and P-5 (confidence on Artifact base)."""
from __future__ import annotations

import pytest

from hi_agent.artifacts.contracts import (
    Artifact,
    EvidenceArtifact,
)
from hi_agent.contracts.provenance import Provenance
from hi_agent.memory.l0_raw import RawEventRecord


# ---------------------------------------------------------------------------
# P-1: Provenance dataclass
# ---------------------------------------------------------------------------


class TestProvenance:
    """Tests for the Provenance data contract."""

    def test_defaults(self) -> None:
        """All fields default to empty string."""
        p = Provenance()
        assert p.url == ""
        assert p.title == ""
        assert p.source_type == ""
        assert p.retrieved_at == ""

    def test_with_values(self) -> None:
        """Explicit values are stored correctly."""
        p = Provenance(
            url="https://example.com/doc",
            title="Example Doc",
            source_type="web",
            retrieved_at="2026-04-16T00:00:00Z",
        )
        assert p.url == "https://example.com/doc"
        assert p.title == "Example Doc"
        assert p.source_type == "web"
        assert p.retrieved_at == "2026-04-16T00:00:00Z"

    def test_source_type_variants(self) -> None:
        """Common source_type values are accepted."""
        for source_type in ("web", "pdf", "api", "user_input", "llm_inference"):
            p = Provenance(source_type=source_type)
            assert p.source_type == source_type


# ---------------------------------------------------------------------------
# P-1: RawEventRecord provenance field
# ---------------------------------------------------------------------------


class TestRawEventRecordProvenance:
    """Tests for provenance field on RawEventRecord."""

    def test_provenance_defaults_to_none(self) -> None:
        """provenance field is None when not supplied."""
        r = RawEventRecord(event_type="test", payload={})
        assert r.provenance is None

    def test_provenance_kwarg_accepted(self) -> None:
        """RawEventRecord accepts a Provenance instance via kwarg."""
        p = Provenance(url="https://example.com", source_type="web")
        r = RawEventRecord(event_type="fetch", payload={"key": "val"}, provenance=p)
        assert r.provenance is p
        assert r.provenance.url == "https://example.com"

    def test_other_fields_unaffected(self) -> None:
        """Adding provenance field does not break existing positional construction."""
        r = RawEventRecord(event_type="ev", payload={"a": 1})
        assert r.event_type == "ev"
        assert r.payload == {"a": 1}
        assert isinstance(r.timestamp, str)
        assert r.tags == []


# ---------------------------------------------------------------------------
# P-5: confidence on Artifact base
# ---------------------------------------------------------------------------


class TestArtifactConfidence:
    """Tests for confidence field on the Artifact base class."""

    def test_confidence_defaults_to_zero(self) -> None:
        """Artifact base class has confidence defaulting to 0.0."""
        a = Artifact()
        assert hasattr(a, "confidence")
        assert a.confidence == pytest.approx(0.0)

    def test_confidence_settable(self) -> None:
        """confidence can be set to an arbitrary float."""
        a = Artifact(confidence=0.87)
        assert a.confidence == pytest.approx(0.87)

    def test_evidence_artifact_inherits_confidence(self) -> None:
        """EvidenceArtifact inherits confidence from Artifact base."""
        e = EvidenceArtifact(claim="sky is blue", confidence=0.95)
        assert e.confidence == pytest.approx(0.95)

    def test_evidence_artifact_confidence_default(self) -> None:
        """EvidenceArtifact confidence defaults to 0.0 (inherited from base)."""
        e = EvidenceArtifact(claim="test claim")
        assert e.confidence == pytest.approx(0.0)

    def test_confidence_in_to_dict(self) -> None:
        """confidence appears in to_dict() output."""
        a = Artifact(confidence=0.5)
        d = a.to_dict()
        assert "confidence" in d
        assert d["confidence"] == pytest.approx(0.5)

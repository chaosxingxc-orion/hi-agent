"""Tests for hi_agent.artifacts contracts and registry."""

from __future__ import annotations

from hi_agent.artifacts.contracts import (
    Artifact,
    DocumentArtifact,
    EvaluationArtifact,
    EvidenceArtifact,
    ResourceArtifact,
    StructuredDataArtifact,
)
from hi_agent.artifacts.registry import ArtifactRegistry

# ---------------------------------------------------------------------------
# Artifact base
# ---------------------------------------------------------------------------


class TestArtifactBase:
    def test_default_id_generated(self):
        a = Artifact()
        assert len(a.artifact_id) == 12

    def test_unique_ids(self):
        ids = {Artifact().artifact_id for _ in range(20)}
        assert len(ids) == 20

    def test_created_at_is_iso(self):
        a = Artifact()
        from datetime import datetime

        # Must parse without error
        datetime.fromisoformat(a.created_at)

    def test_to_dict_roundtrip(self):
        a = Artifact(
            artifact_id="abc123",
            artifact_type="base",
            producer_action_id="act-1",
            source_refs=["ref-1"],
            metadata={"key": "value"},
            content="hello",
        )
        d = a.to_dict()
        assert d["artifact_id"] == "abc123"
        assert d["producer_action_id"] == "act-1"
        assert d["source_refs"] == ["ref-1"]
        assert d["metadata"] == {"key": "value"}
        assert d["content"] == "hello"


# ---------------------------------------------------------------------------
# ResourceArtifact
# ---------------------------------------------------------------------------


class TestResourceArtifact:
    def test_type_forced(self):
        r = ResourceArtifact(url="http://example.com", title="Example", snippet="hi")
        assert r.artifact_type == "resource"

    def test_to_dict_includes_url(self):
        r = ResourceArtifact(url="http://a.com", title="A", snippet="snip")
        d = r.to_dict()
        assert d["url"] == "http://a.com"
        assert d["title"] == "A"
        assert d["snippet"] == "snip"

    def test_from_dict_roundtrip(self):
        r = ResourceArtifact(
            artifact_id="r001",
            url="http://b.com",
            title="B",
            snippet="test",
            producer_action_id="p1",
        )
        d = r.to_dict()
        r2 = ResourceArtifact.from_dict(d)
        assert r2.artifact_id == "r001"
        assert r2.url == "http://b.com"
        assert r2.artifact_type == "resource"


# ---------------------------------------------------------------------------
# DocumentArtifact
# ---------------------------------------------------------------------------


class TestDocumentArtifact:
    def test_type_forced(self):
        d = DocumentArtifact()
        assert d.artifact_type == "document"

    def test_fields(self):
        doc = DocumentArtifact(
            url="http://docs.example.com",
            title="Guide",
            text="Lorem ipsum",
            word_count=2,
        )
        d = doc.to_dict()
        assert d["url"] == "http://docs.example.com"
        assert d["word_count"] == 2

    def test_from_dict_roundtrip(self):
        doc = DocumentArtifact(
            artifact_id="d001", url="http://x.com", title="X", text="body", word_count=1
        )
        restored = DocumentArtifact.from_dict(doc.to_dict())
        assert restored.text == "body"
        assert restored.artifact_type == "document"


# ---------------------------------------------------------------------------
# StructuredDataArtifact
# ---------------------------------------------------------------------------


class TestStructuredDataArtifact:
    def test_type_forced(self):
        s = StructuredDataArtifact()
        assert s.artifact_type == "structured_data"

    def test_from_dict_roundtrip(self):
        s = StructuredDataArtifact(
            artifact_id="s001",
            schema_id="revenue_schema",
            data={"q1": 100, "q2": 200},
        )
        s2 = StructuredDataArtifact.from_dict(s.to_dict())
        assert s2.schema_id == "revenue_schema"
        assert s2.data == {"q1": 100, "q2": 200}


# ---------------------------------------------------------------------------
# EvidenceArtifact
# ---------------------------------------------------------------------------


class TestEvidenceArtifact:
    def test_type_forced(self):
        e = EvidenceArtifact()
        assert e.artifact_type == "evidence"

    def test_evidence_type_default(self):
        e = EvidenceArtifact(claim="The sky is blue", confidence=0.9)
        assert e.evidence_type == "direct"

    def test_from_dict_roundtrip(self):
        e = EvidenceArtifact(
            artifact_id="e001",
            claim="fact",
            confidence=0.8,
            evidence_type="indirect",
        )
        e2 = EvidenceArtifact.from_dict(e.to_dict())
        assert e2.confidence == 0.8
        assert e2.evidence_type == "indirect"


# ---------------------------------------------------------------------------
# EvaluationArtifact
# ---------------------------------------------------------------------------


class TestEvaluationArtifact:
    def test_type_forced(self):
        ev = EvaluationArtifact()
        assert ev.artifact_type == "evaluation"

    def test_from_dict_roundtrip(self):
        ev = EvaluationArtifact(
            artifact_id="v001",
            score=0.85,
            passed=True,
            criteria={"completeness": True, "accuracy": False},
            feedback="mostly good",
        )
        ev2 = EvaluationArtifact.from_dict(ev.to_dict())
        assert ev2.score == 0.85
        assert ev2.passed is True
        assert ev2.criteria["completeness"] is True


# ---------------------------------------------------------------------------
# ArtifactRegistry
# ---------------------------------------------------------------------------


class TestArtifactRegistry:
    def test_store_and_get(self):
        reg = ArtifactRegistry()
        a = ResourceArtifact(artifact_id="x1", url="http://test.com", title="T", snippet="")
        reg.store(a)
        assert reg.get("x1") is a

    def test_get_missing_returns_none(self):
        reg = ArtifactRegistry()
        assert reg.get("nonexistent") is None

    def test_count(self):
        reg = ArtifactRegistry()
        reg.store(Artifact(artifact_id="a1"))
        reg.store(Artifact(artifact_id="a2"))
        assert reg.count() == 2

    def test_clear(self):
        reg = ArtifactRegistry()
        reg.store(Artifact(artifact_id="a1"))
        reg.clear()
        assert reg.count() == 0

    def test_all(self):
        reg = ArtifactRegistry()
        a1 = Artifact(artifact_id="a1")
        a2 = Artifact(artifact_id="a2")
        reg.store(a1)
        reg.store(a2)
        assert set(reg.all()) == {a1, a2}

    def test_query_by_type(self):
        reg = ArtifactRegistry()
        r = ResourceArtifact(artifact_id="r1", url="u", title="t", snippet="s")
        d = DocumentArtifact(artifact_id="d1")
        reg.store(r)
        reg.store(d)
        resources = reg.query(artifact_type="resource")
        assert len(resources) == 1
        assert resources[0].artifact_id == "r1"

    def test_query_by_producer(self):
        reg = ArtifactRegistry()
        a1 = Artifact(artifact_id="a1", producer_action_id="act-search")
        a2 = Artifact(artifact_id="a2", producer_action_id="act-extract")
        reg.store(a1)
        reg.store(a2)
        results = reg.query(producer_action_id="act-search")
        assert len(results) == 1
        assert results[0].artifact_id == "a1"

    def test_query_combined_filters(self):
        reg = ArtifactRegistry()
        r1 = ResourceArtifact(artifact_id="r1", url="u", title="t", snippet="s")
        r1.producer_action_id = "act-1"
        r2 = ResourceArtifact(artifact_id="r2", url="u2", title="t2", snippet="")
        r2.producer_action_id = "act-2"
        reg.store(r1)
        reg.store(r2)
        results = reg.query(artifact_type="resource", producer_action_id="act-1")
        assert len(results) == 1
        assert results[0].artifact_id == "r1"

    def test_overwrite_same_id(self):
        reg = ArtifactRegistry()
        a1 = Artifact(artifact_id="same")
        a2 = Artifact(artifact_id="same", producer_action_id="updated")
        reg.store(a1)
        reg.store(a2)
        assert reg.count() == 1
        assert reg.get("same").producer_action_id == "updated"

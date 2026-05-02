"""Integration tests for artifact-first evidence persistence."""

from __future__ import annotations

from hi_agent.artifacts.adapters import OutputToArtifactAdapter
from hi_agent.artifacts.contracts import (
    Artifact,
    DocumentArtifact,
    EvaluationArtifact,
    EvidenceArtifact,
    ResourceArtifact,
    StructuredDataArtifact,
)
from hi_agent.artifacts.registry import ArtifactRegistry


class TestOutputToArtifactAdapter:
    def _adapt(self, output):
        return OutputToArtifactAdapter().adapt("act-1", output)

    def test_none_output_returns_empty(self):
        assert self._adapt(None) == []

    def test_resource_artifact_from_url_and_title(self):
        artifacts = self._adapt(
            {"url": "http://example.com", "title": "Example", "snippet": "A snippet"}
        )
        assert len(artifacts) == 1
        a = artifacts[0]
        assert isinstance(a, ResourceArtifact)
        assert a.url == "http://example.com"
        assert a.title == "Example"
        assert a.producer_action_id == "act-1"

    def test_evidence_artifact_from_claim_and_confidence(self):
        artifacts = self._adapt({"claim": "Revenue grew", "confidence": 0.9})
        assert len(artifacts) == 1
        a = artifacts[0]
        assert isinstance(a, EvidenceArtifact)
        assert a.claim == "Revenue grew"
        assert a.confidence == 0.9

    def test_evaluation_artifact_from_score_and_passed(self):
        artifacts = self._adapt({"score": 0.85, "passed": True, "feedback": "good"})
        assert len(artifacts) == 1
        a = artifacts[0]
        assert isinstance(a, EvaluationArtifact)
        assert a.score == 0.85
        assert a.passed is True

    def test_structured_data_artifact(self):
        artifacts = self._adapt({"schema_id": "revenue", "data": {"q1": 100}})
        assert len(artifacts) == 1
        a = artifacts[0]
        assert isinstance(a, StructuredDataArtifact)
        assert a.schema_id == "revenue"

    def test_document_artifact_url_only(self):
        artifacts = self._adapt({"url": "http://docs.example.com", "text": "body"})
        assert len(artifacts) == 1
        assert isinstance(artifacts[0], DocumentArtifact)

    def test_base_artifact_fallback(self):
        artifacts = self._adapt({"some_key": "some_value"})
        assert len(artifacts) == 1
        assert isinstance(artifacts[0], Artifact)
        assert artifacts[0].artifact_type == "base"

    def test_non_dict_output_wrapped(self):
        artifacts = self._adapt("plain string output")
        assert len(artifacts) == 1
        assert isinstance(artifacts[0], Artifact)

    def test_source_refs_propagated(self):
        adapter = OutputToArtifactAdapter()
        artifacts = adapter.adapt("act-2", {"output": "x"}, source_refs=["art-001"])
        assert artifacts[0].source_refs == ["art-001"]

    def test_provenance_populated_by_adapter(self):
        """Adapter populates provenance dict on all artifacts."""
        artifacts = self._adapt({"url": "http://example.com", "title": "T", "snippet": "s"})
        a = artifacts[0]
        assert "capability_action_id" in a.provenance
        assert a.provenance["capability_action_id"] == "act-1"

    def test_upstream_artifact_ids_default_empty(self):
        """upstream_artifact_ids defaults to empty list."""
        artifacts = self._adapt({"claim": "test", "confidence": 0.8})
        assert artifacts[0].upstream_artifact_ids == []


class TestHarnessExecutorArtifactRegistry:
    def test_harness_stores_artifacts_on_execute(self):
        from hi_agent.runtime.harness.contracts import ActionSpec
        from hi_agent.runtime.harness.executor import HarnessExecutor
        from hi_agent.runtime.harness.governance import GovernanceEngine

        registry = ArtifactRegistry()
        output = {"url": "http://example.com", "title": "Test", "snippet": "snip"}

        # Mock invoker
        class MockInvoker:
            def invoke(self, name, payload):
                return output

        from hi_agent.runtime.harness.evidence_store import EvidenceStore

        harness = HarnessExecutor(
            governance=GovernanceEngine(),
            capability_invoker=MockInvoker(),
            artifact_registry=registry,
            evidence_store=EvidenceStore(),
        )
        spec = ActionSpec(
            action_id="act-test",
            action_type="read",
            capability_name="search",
            payload={"query": "test"},
        )
        _ = harness.execute(spec)
        # Artifact should be stored
        assert registry.count() == 1
        arts = registry.query(artifact_type="resource")
        assert len(arts) == 1
        assert arts[0].url == "http://example.com"

    def test_harness_without_registry_still_works(self):
        """HarnessExecutor works normally without artifact_registry."""
        from hi_agent.runtime.harness.contracts import ActionSpec
        from hi_agent.runtime.harness.executor import HarnessExecutor
        from hi_agent.runtime.harness.governance import GovernanceEngine

        class MockInvoker:
            def invoke(self, name, payload):
                return {"output": "result"}

        from hi_agent.runtime.harness.evidence_store import EvidenceStore

        harness = HarnessExecutor(
            governance=GovernanceEngine(),
            capability_invoker=MockInvoker(),
            artifact_registry=None,
            evidence_store=EvidenceStore(),
        )
        spec = ActionSpec(action_id="act-1", action_type="read", capability_name="cap", payload={})
        result = harness.execute(spec)
        assert result.output == {"output": "result"}


class TestBuilderCreatesArtifactRegistry:
    def test_builder_builds_artifact_registry(self):
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        reg = builder.build_artifact_registry()
        assert reg is not None

    def test_builder_artifact_registry_is_singleton(self):
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        r1 = builder.build_artifact_registry()
        r2 = builder.build_artifact_registry()
        assert r1 is r2

    def test_artifact_has_provenance_fields(self):
        """Artifact base class has provenance and upstream_artifact_ids fields."""
        from hi_agent.artifacts.contracts import Artifact

        a = Artifact(producer_action_id="test-action")
        assert hasattr(a, "provenance")
        assert hasattr(a, "upstream_artifact_ids")
        assert isinstance(a.provenance, dict)
        assert isinstance(a.upstream_artifact_ids, list)


class TestArtifactRegistryQuerySurface:
    def test_query_by_source_ref(self):
        """Can query artifacts by source_ref."""
        from hi_agent.artifacts.contracts import EvidenceArtifact

        registry = ArtifactRegistry()
        a1 = EvidenceArtifact(producer_action_id="act-1", claim="C", confidence=0.9)
        a1.source_refs = ["src-upstream"]
        registry.store(a1)

        results = registry.query_by_source_ref("src-upstream")
        assert len(results) == 1
        assert results[0].artifact_id == a1.artifact_id

        empty = registry.query_by_source_ref("nonexistent")
        assert empty == []

    def test_query_by_upstream(self):
        """Can query artifacts by upstream_artifact_ids."""
        from hi_agent.artifacts.contracts import Artifact

        registry = ArtifactRegistry()
        a = Artifact(producer_action_id="act-2")
        a.upstream_artifact_ids = ["parent-123"]
        registry.store(a)

        results = registry.query_by_upstream("parent-123")
        assert len(results) == 1

        empty = registry.query_by_upstream("missing")
        assert empty == []

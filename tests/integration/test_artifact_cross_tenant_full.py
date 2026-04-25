"""Track D: artifact registry enforces tenant isolation for list/get/provenance."""
from __future__ import annotations

import pytest


def _make_artifact(aid: str, tenant_id: str, project_id: str = "p1"):
    from hi_agent.artifacts.contracts import Artifact

    return Artifact(
        artifact_id=aid,
        artifact_type="text",
        content="data",
        producer_action_id="act1",
        tenant_id=tenant_id,
        project_id=project_id,
    )


@pytest.fixture(autouse=True)
def _dev_posture(monkeypatch):
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


def test_registry_get_correct_tenant():
    """Correct tenant can retrieve its own artifact."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    a1 = _make_artifact("a1", "tenant-A")
    reg.store(a1)
    assert reg.get("a1", tenant_id="tenant-A") is not None


def test_registry_get_wrong_tenant_returns_none():
    """Wrong tenant gets None (not the artifact)."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    assert reg.get("a1", tenant_id="tenant-B") is None


def test_registry_get_no_tenant_filter_returns_artifact():
    """Omitting tenant_id (None) disables filter — used by internal/admin callers."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    assert reg.get("a1") is not None
    assert reg.get("a1", tenant_id=None) is not None


def test_registry_get_empty_tenant_no_filter():
    """Empty string tenant_id also disables filter (backwards compat)."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    assert reg.get("a1", tenant_id="") is not None


def test_registry_get_legacy_artifact_no_tenant_field():
    """Artifact with empty tenant_id is accessible to any tenant (dev compat)."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    legacy = _make_artifact("leg1", "")  # legacy: tenant_id=""
    reg.store(legacy)
    assert reg.get("leg1", tenant_id="tenant-X") is not None


def test_registry_query_filters_by_tenant():
    """query(tenant_id=) returns only artifacts matching that tenant."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    reg.store(_make_artifact("a2", "tenant-B"))
    reg.store(_make_artifact("a3", "tenant-A"))

    results = reg.query(tenant_id="tenant-A")
    ids = {a.artifact_id for a in results}
    assert ids == {"a1", "a3"}


def test_registry_query_no_tenant_returns_all():
    """query() without tenant_id returns all artifacts."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    reg.store(_make_artifact("a2", "tenant-B"))
    assert len(reg.query()) == 2


def test_registry_all_with_tenant():
    """all(tenant_id=) filters correctly."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    reg.store(_make_artifact("a2", "tenant-B"))

    assert len(reg.all(tenant_id="tenant-A")) == 1
    assert reg.all(tenant_id="tenant-A")[0].artifact_id == "a1"


def test_registry_count_with_tenant():
    """count(tenant_id=) counts only matching artifacts."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    reg.store(_make_artifact("a1", "tenant-A"))
    reg.store(_make_artifact("a2", "tenant-B"))
    reg.store(_make_artifact("a3", "tenant-A"))

    assert reg.count(tenant_id="tenant-A") == 2
    assert reg.count(tenant_id="tenant-B") == 1
    assert reg.count() == 3


def test_registry_query_by_source_ref_tenant_filter():
    """query_by_source_ref with tenant_id filters by tenant."""
    from hi_agent.artifacts.contracts import Artifact
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    a1 = Artifact(
        artifact_id="a1",
        artifact_type="text",
        content="d",
        producer_action_id="act",
        tenant_id="tenant-A",
        source_refs=["src1"],
    )
    a2 = Artifact(
        artifact_id="a2",
        artifact_type="text",
        content="d",
        producer_action_id="act",
        tenant_id="tenant-B",
        source_refs=["src1"],
    )
    reg.store(a1)
    reg.store(a2)

    results_a = reg.query_by_source_ref("src1", tenant_id="tenant-A")
    assert len(results_a) == 1
    assert results_a[0].artifact_id == "a1"


def test_registry_query_by_upstream_tenant_filter():
    """query_by_upstream with tenant_id filters by tenant."""
    from hi_agent.artifacts.contracts import Artifact
    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry()
    a1 = Artifact(
        artifact_id="a1",
        artifact_type="text",
        content="d",
        producer_action_id="act",
        tenant_id="tenant-A",
        upstream_artifact_ids=["upstream1"],
    )
    a2 = Artifact(
        artifact_id="a2",
        artifact_type="text",
        content="d",
        producer_action_id="act",
        tenant_id="tenant-B",
        upstream_artifact_ids=["upstream1"],
    )
    reg.store(a1)
    reg.store(a2)

    results_a = reg.query_by_upstream("upstream1", tenant_id="tenant-A")
    assert len(results_a) == 1
    assert results_a[0].artifact_id == "a1"

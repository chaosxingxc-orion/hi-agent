"""HD-4: ArtifactRegistry empty-tenant filter is posture-aware (W24-J4).

Under research/prod posture, an artifact with empty tenant_id MUST NOT match
a tenant-scoped query. Under dev posture, the legacy lenient match is retained
but admission is countable and the call is logged.

Complements ``test_artifact_legacy_tenantless_posture_aware.py`` (which only
covers ``get()``); this module verifies that ``query()``, ``all()``,
``query_by_source_ref``, and ``query_by_upstream`` honour the same posture
discipline.
"""

from __future__ import annotations

import pytest
from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.metrics import (
    legacy_tenantless_denied_total,
    legacy_tenantless_visible_total,
)
from hi_agent.artifacts.registry import ArtifactRegistry


def _new_registry() -> ArtifactRegistry:
    """Build an in-memory ArtifactRegistry without invoking the posture gate.

    The constructor refuses to build under research/prod, so the existing
    artifact tests use ``__new__`` + ``_store = {}`` to install fixtures
    independent of the posture under test.
    """
    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    return reg


@pytest.fixture(autouse=True)
def _reset_counters() -> None:
    legacy_tenantless_denied_total.reset()
    legacy_tenantless_visible_total.reset()


def test_research_posture_query_excludes_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """``query(tenant_id=...)`` excludes legacy tenantless artifacts under strict posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    reg = _new_registry()
    legacy = Artifact(artifact_id="legacy-q", artifact_type="base", tenant_id="")
    owned = Artifact(artifact_id="owned-q", artifact_type="base", tenant_id="tenant-A")
    reg._store[legacy.artifact_id] = legacy
    reg._store[owned.artifact_id] = owned

    matched_ids = {a.artifact_id for a in reg.query(tenant_id="tenant-A")}

    assert "owned-q" in matched_ids
    assert "legacy-q" not in matched_ids
    assert legacy_tenantless_denied_total.total() >= 1


def test_research_posture_all_excludes_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """``all(tenant_id=...)`` excludes legacy tenantless artifacts under strict posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    reg = _new_registry()
    legacy = Artifact(artifact_id="legacy-a", artifact_type="base", tenant_id="")
    owned = Artifact(artifact_id="owned-a", artifact_type="base", tenant_id="tenant-A")
    reg._store[legacy.artifact_id] = legacy
    reg._store[owned.artifact_id] = owned

    visible_ids = {a.artifact_id for a in reg.all(tenant_id="tenant-A")}

    assert "owned-a" in visible_ids
    assert "legacy-a" not in visible_ids


def test_research_posture_query_by_source_ref_excludes_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    reg = _new_registry()
    leak = Artifact(
        artifact_id="leak-src",
        artifact_type="base",
        tenant_id="",
        source_refs=["src-1"],
    )
    reg._store[leak.artifact_id] = leak

    assert reg.query_by_source_ref("src-1", tenant_id="tenant-A") == []


def test_research_posture_query_by_upstream_excludes_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    reg = _new_registry()
    leak = Artifact(
        artifact_id="leak-up",
        artifact_type="base",
        tenant_id="",
        upstream_artifact_ids=["up-1"],
    )
    reg._store[leak.artifact_id] = leak

    assert reg.query_by_upstream("up-1", tenant_id="tenant-A") == []


def test_dev_posture_query_admits_legacy_with_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev posture preserves legacy lenient match and increments visibility counter."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    reg = _new_registry()
    legacy = Artifact(artifact_id="legacy-dev-q", artifact_type="base", tenant_id="")
    reg._store[legacy.artifact_id] = legacy

    matched = reg.query(tenant_id="tenant-A")
    assert any(a.artifact_id == "legacy-dev-q" for a in matched)
    assert legacy_tenantless_visible_total.total() >= 1

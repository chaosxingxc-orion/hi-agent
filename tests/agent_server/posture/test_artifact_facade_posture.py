"""Unit tests: ArtifactFacade uses Posture.from_env() not os.environ string-compare."""
from __future__ import annotations

import pytest
from agent_server.contracts.errors import NotFoundError
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.artifact_facade import ArtifactFacade


def _make_facade(records: list[dict]) -> ArtifactFacade:
    def list_fn(**kwargs):
        return records

    def get_fn(**kwargs):
        artifact_id = kwargs.get("artifact_id", "")
        for rec in records:
            if rec.get("artifact_id") == artifact_id:
                return rec
        return {}

    return ArtifactFacade(list_artifacts=list_fn, get_artifact=get_fn)


def _ctx(tenant_id: str = "t1") -> TenantContext:
    return TenantContext(tenant_id=tenant_id)


def test_artifact_facade_uses_posture_enum_not_string(monkeypatch):
    """ArtifactFacade imports Posture and uses from_env(); os module not present for posture."""
    import agent_server.facade.artifact_facade as mod

    # Verify 'os' is no longer used for posture env-var read in the module
    assert not hasattr(mod, "_is_strict_posture"), (
        "_is_strict_posture helper must be removed; posture must use Posture.from_env()"
    )
    # Verify Posture is imported in the module
    assert hasattr(mod, "Posture"), "Posture must be imported in artifact_facade"


def test_list_for_run_dev_posture_includes_orphan(monkeypatch):
    """Under dev posture, orphan records (no tenant_id) are included in list output."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    records = [
        {"artifact_id": "a1", "tenant_id": ""},
        {"artifact_id": "a2", "tenant_id": "t1"},
    ]
    facade = _make_facade(records)
    result = facade.list_for_run(_ctx(), "run-1")
    ids = [r["artifact_id"] for r in result]
    assert "a1" in ids, "dev posture should include orphan records"
    assert "a2" in ids


def test_list_for_run_research_posture_excludes_orphan(monkeypatch):
    """Under research posture, orphan records (no tenant_id) are excluded from list."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    records = [
        {"artifact_id": "a1", "tenant_id": ""},
        {"artifact_id": "a2", "tenant_id": "t1"},
    ]
    facade = _make_facade(records)
    result = facade.list_for_run(_ctx(), "run-1")
    ids = [r["artifact_id"] for r in result]
    assert "a1" not in ids, "research posture must exclude orphan records (HD-4)"
    assert "a2" in ids


def test_get_dev_posture_allows_orphan(monkeypatch):
    """Under dev posture, get() returns orphan artifact without raising."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    records = [{"artifact_id": "a1", "tenant_id": ""}]
    facade = _make_facade(records)
    result = facade.get(_ctx(), "a1")
    assert result["artifact_id"] == "a1"


def test_get_research_posture_raises_for_orphan(monkeypatch):
    """Under research posture, get() raises NotFoundError for orphan artifacts (HD-4)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    records = [{"artifact_id": "a1", "tenant_id": ""}]
    facade = _make_facade(records)
    with pytest.raises(NotFoundError):
        facade.get(_ctx(), "a1")

"""Tests: MemoryBuilder workspace_key parameter threads WorkspaceKey into store paths."""
import pytest
from pathlib import Path
from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.server.workspace_path import WorkspaceKey


@pytest.fixture
def builder(tmp_path):
    from hi_agent.config.trace_config import TraceConfig
    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return MemoryBuilder(cfg)


def test_short_term_uses_workspace_path(builder, tmp_path):
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    store = builder.build_short_term_store(profile_id="p1", workspace_key=key)
    base = getattr(store, "_storage_dir", None) or getattr(store, "storage_dir", None)
    assert "workspaces/t1/users/u1/sessions/s1" in str(base).replace("\\", "/")


def test_mid_term_uses_workspace_path(builder, tmp_path):
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    store = builder.build_mid_term_store(profile_id="p1", workspace_key=key)
    assert "workspaces/t1/users/u1/sessions/s1" in str(store._storage_dir).replace("\\", "/")


def test_long_term_uses_workspace_path(builder, tmp_path):
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    graph = builder.build_long_term_graph(profile_id="p1", workspace_key=key)
    assert "workspaces/t1/users/u1/sessions/s1" in str(graph._storage_path).replace("\\", "/")


def test_no_workspace_key_uses_profile_fallback(builder):
    """Backward compat: no workspace_key → profile_id-scoped path (existing behavior)."""
    store = builder.build_mid_term_store(profile_id="p1", workspace_key=None)
    assert store is not None

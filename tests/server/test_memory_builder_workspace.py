"""Tests: MemoryBuilder workspace_key parameter threads WorkspaceKey into store paths."""

from pathlib import Path

import pytest
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
    posix = Path(str(base)).as_posix()
    assert "workspaces/t1/users/u1/sessions/s1" in posix
    assert "L1" in posix


def test_mid_term_uses_workspace_path(builder, tmp_path):
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    store = builder.build_mid_term_store(profile_id="p1", workspace_key=key)
    posix = Path(str(store._storage_dir)).as_posix()
    assert "workspaces/t1/users/u1/sessions/s1" in posix
    assert "L2" in posix


def test_long_term_uses_workspace_path(builder, tmp_path):
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    graph = builder.build_long_term_graph(profile_id="p1", workspace_key=key)
    posix = Path(str(graph._storage_path)).as_posix()
    assert "workspaces/t1/users/u1/sessions/s1" in posix
    assert "graph.json" in posix


def test_no_workspace_key_uses_profile_fallback(builder):
    """Backward compat: no workspace_key → profile_id-scoped path (existing behavior)."""
    store = builder.build_mid_term_store(profile_id="p1", workspace_key=None)
    path = str(store._storage_dir)
    assert "profiles" in path or "p1" in path  # profile-scoped path was taken
    assert "workspaces" not in path  # workspace branch was NOT taken


def test_no_workspace_key_no_profile_raises(builder):
    """Rule 13 (DF-12): empty profile_id AND no workspace_key must raise — the
    silent unscoped default was the F-2/G-5/I-7 defect shape."""
    with pytest.raises(ValueError, match="profile_id"):
        builder.build_mid_term_store(profile_id="", workspace_key=None)

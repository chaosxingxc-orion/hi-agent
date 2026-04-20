"""Acceptance tests 11-15: memory storage isolation.
Same profile_id, different workspace -> zero cross-contamination.
"""
from pathlib import Path

import pytest
from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.server.workspace_path import WorkspaceKey, WorkspacePathHelper


@pytest.fixture
def builder(tmp_path):
    from hi_agent.config.trace_config import TraceConfig
    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return MemoryBuilder(cfg)


def test_11_stm_no_cross_user_contamination(builder):
    """Acceptance test 11: Two users with same profile_id do not share short-term memory."""
    key_a = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    key_b = WorkspaceKey(tenant_id="t1", user_id="u2", session_id="s2")
    stm_a = builder.build_short_term_store(profile_id="same_profile", workspace_key=key_a)
    stm_b = builder.build_short_term_store(profile_id="same_profile", workspace_key=key_b)

    path_a = Path(str(stm_a._storage_dir)).as_posix()
    path_b = Path(str(stm_b._storage_dir)).as_posix()

    assert path_a != path_b
    assert "u1" in path_a
    assert "u2" in path_b


def test_12_mid_term_no_cross_user_contamination(builder):
    """Acceptance test 12: Two users do not share mid-term memory."""
    key_a = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    key_b = WorkspaceKey(tenant_id="t1", user_id="u2", session_id="s2")
    mid_a = builder.build_mid_term_store(profile_id="same_profile", workspace_key=key_a)
    mid_b = builder.build_mid_term_store(profile_id="same_profile", workspace_key=key_b)

    path_a = Path(str(mid_a._storage_dir)).as_posix()
    path_b = Path(str(mid_b._storage_dir)).as_posix()

    assert path_a != path_b
    assert "u1" in path_a
    assert "u2" in path_b


def test_13_l3_no_cross_user_contamination(builder):
    """Acceptance test 13: Two users do not share L3 graph nodes."""
    key_a = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    key_b = WorkspaceKey(tenant_id="t1", user_id="u2", session_id="s2")
    graph_a = builder.build_long_term_graph(profile_id="same_profile", workspace_key=key_a)
    graph_b = builder.build_long_term_graph(profile_id="same_profile", workspace_key=key_b)

    path_a = Path(str(graph_a._storage_path)).as_posix()
    path_b = Path(str(graph_b._storage_path)).as_posix()

    assert path_a != path_b
    assert "u1" in path_a
    assert "u2" in path_b


def test_14_workspace_paths_are_distinct(tmp_path):
    """Acceptance test 14: Different workspaces produce distinct paths."""
    key_a = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    key_b = WorkspaceKey(tenant_id="t1", user_id="u2", session_id="s2")
    path_a = WorkspacePathHelper.private(tmp_path, key_a, "cache", "index.json")
    path_b = WorkspacePathHelper.private(tmp_path, key_b, "cache", "index.json")
    assert path_a != path_b


def test_15_l0_and_checkpoint_under_workspace_paths(tmp_path):
    """Acceptance test 15: L0 raw memory and checkpoints under workspace-scoped paths."""
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    l0_path = WorkspacePathHelper.private(tmp_path, key, "L0")
    checkpoint_path = WorkspacePathHelper.private(tmp_path, key, "checkpoints")

    l0_posix = Path(l0_path).as_posix()
    cp_posix = Path(checkpoint_path).as_posix()

    assert "workspaces/t1/users/u1/sessions/s1" in l0_posix
    assert "L0" in l0_posix
    assert "workspaces/t1/users/u1/sessions/s1" in cp_posix
    assert "checkpoints" in cp_posix

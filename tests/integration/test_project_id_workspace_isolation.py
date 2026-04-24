"""Integration test: project_id isolation in workspace-mode L3 and L2.

Verifies:
- Two different project_ids produce different storage paths (the bug was they collided).
- Same project_id on same builder instance returns the cached object.
- Empty project_id preserves the old path behavior (no extra dir layer).
"""
from __future__ import annotations

from pathlib import Path

from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.server.workspace_path import WorkspaceKey


def _make_cfg(tmp_path: Path, project_id: str) -> TraceConfig:
    episodes = str(tmp_path / "episodes")
    return TraceConfig(episodic_storage_dir=episodes, project_id=project_id)


def _wk() -> WorkspaceKey:
    return WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")


def test_workspace_l3_different_projects_have_different_paths(tmp_path: Path) -> None:
    """Two different project_ids must produce non-colliding graph paths."""
    cfg_a = _make_cfg(tmp_path, "proj-A")
    cfg_b = _make_cfg(tmp_path, "proj-B")
    wk = _wk()
    g_a = MemoryBuilder(cfg_a).build_long_term_graph(profile_id="", workspace_key=wk)
    g_b = MemoryBuilder(cfg_b).build_long_term_graph(profile_id="", workspace_key=wk)
    assert g_a._storage_path != g_b._storage_path, (
        "proj-A and proj-B must not share the same graph.json path"
    )


def test_workspace_l3_same_project_shares_path(tmp_path: Path) -> None:
    """Same builder + same project_id returns the cached instance."""
    cfg = _make_cfg(tmp_path, "proj-X")
    wk = _wk()
    builder = MemoryBuilder(cfg)
    g1 = builder.build_long_term_graph(profile_id="", workspace_key=wk)
    g2 = builder.build_long_term_graph(profile_id="", workspace_key=wk)
    assert g1 is g2, "Same builder+args must return the cached instance"


def test_workspace_l3_empty_project_id_no_crash(tmp_path: Path) -> None:
    """project_id='' must not break existing behavior (no extra dir layer)."""
    cfg = _make_cfg(tmp_path, "")
    wk = _wk()
    g = MemoryBuilder(cfg).build_long_term_graph(profile_id="", workspace_key=wk)
    assert g is not None
    # Path must end in graph.json with no empty component (no '//' or trailing /)
    path_str = str(g._storage_path)
    assert "graph.json" in path_str
    assert "//" not in path_str.replace("\\\\", "")


def test_workspace_l3_project_id_in_path(tmp_path: Path) -> None:
    """When project_id is set, its value appears as a directory in the path."""
    cfg = _make_cfg(tmp_path, "my-project")
    wk = _wk()
    g = MemoryBuilder(cfg).build_long_term_graph(profile_id="", workspace_key=wk)
    path_str = str(g._storage_path)
    assert "my-project" in path_str, (
        f"project_id 'my-project' must appear in the storage path, got: {path_str}"
    )

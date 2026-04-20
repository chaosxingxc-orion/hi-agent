# tests/server/test_builder_workspace_paths.py
"""Tests: WorkspaceKey threads workspace-scoped paths into RunExecutor memory stores."""
from pathlib import Path

from hi_agent.server.workspace_path import WorkspaceKey


def test_build_executor_uses_workspace_scoped_paths(tmp_path):
    """Memory stores inside a run executor should use workspace-scoped paths."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.contracts import TaskContract

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = SystemBuilder(cfg)
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")

    contract = TaskContract(task_id="test-run-1", goal="test goal")
    executor = builder.build_executor(contract, workspace_key=key)

    mid_term = getattr(executor, "mid_term_store", None)
    assert mid_term is not None, "executor must expose mid_term_store"
    path = Path(mid_term._storage_dir).as_posix()
    assert "workspaces/t1/users/u1/sessions/s1" in path
    assert "L2" in path


def test_build_executor_workspace_key_none_uses_default(tmp_path):
    """workspace_key=None preserves existing behavior (no workspace subdir)."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.contracts import TaskContract

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = SystemBuilder(cfg)

    contract = TaskContract(task_id="test-run-2", goal="test goal")
    executor = builder.build_executor(contract, workspace_key=None)

    mid_term = getattr(executor, "mid_term_store", None)
    assert mid_term is not None
    path = Path(mid_term._storage_dir).as_posix()
    assert "workspaces" not in path


def test_build_executor_raw_memory_uses_workspace_scoped_path(tmp_path):
    """RawMemoryStore base_dir should be workspace-scoped when workspace_key is provided."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.contracts import TaskContract

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = SystemBuilder(cfg)
    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")

    contract = TaskContract(task_id="test-run-3", goal="test goal")
    executor = builder.build_executor(contract, workspace_key=key)

    raw_memory = getattr(executor, "raw_memory", None)
    assert raw_memory is not None, "executor must expose raw_memory"
    base_dir = getattr(raw_memory, "_base_dir", None)
    assert base_dir is not None
    path = Path(base_dir).as_posix()
    assert "workspaces/t1/users/u1/sessions/s1" in path
    assert "L0" in path


def test_build_run_executor_empty_user_id_falls_back(tmp_path):
    """Empty user_id in WorkspaceKey must fall back to default paths, not raise ValueError."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.contracts import TaskContract

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = SystemBuilder(cfg)
    key = WorkspaceKey(tenant_id="t1", user_id="", session_id="s1")

    contract = TaskContract(task_id="test-run-4", goal="test goal")
    # Should not raise, should return an executor with non-workspace paths
    executor = builder.build_executor(contract, workspace_key=key)
    mid_term = getattr(executor, "mid_term_store", None)
    if mid_term is not None:
        assert "workspaces" not in Path(mid_term._storage_dir).as_posix()

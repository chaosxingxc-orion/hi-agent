"""Test that RunSession checkpoint uses workspace-scoped directory."""
from pathlib import Path


def test_run_session_checkpoint_uses_workspace_path(tmp_path):
    """RunSession checkpoint must go to workspace-scoped directory."""
    from hi_agent.server.workspace_path import WorkspaceKey, WorkspacePathHelper
    from hi_agent.session.run_session import RunSession

    key = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1")
    storage_dir = str(WorkspacePathHelper.private(tmp_path, key, "checkpoints"))

    session = RunSession(run_id="run-abc", storage_dir=storage_dir)
    path = session.save_checkpoint()
    posix = Path(path).as_posix()
    assert "workspaces/t1/users/u1/sessions/s1" in posix
    assert "checkpoints" in posix


def test_run_session_no_workspace_key_still_works(tmp_path):
    """RunSession without storage_dir still saves to default .checkpoint location."""
    import os

    from hi_agent.session.run_session import RunSession

    orig_dir = os.getcwd()
    os.chdir(str(tmp_path))
    try:
        session = RunSession(run_id="run-no-ws")
        path = session.save_checkpoint()
        assert path is not None
        assert "run-no-ws" in path
    finally:
        os.chdir(orig_dir)

from pathlib import Path

import pytest
from hi_agent.server.workspace_path import WorkspaceKey, WorkspacePathHelper, _safe_slug


def test_safe_slug_normal():
    assert _safe_slug("user-123") == "user-123"


def test_safe_slug_replaces_spaces():
    result = _safe_slug("user 123")
    assert " " not in result
    assert len(result) <= 64


def test_safe_slug_path_traversal_hashed():
    result = _safe_slug("../../../etc/passwd")
    # SHA256 hex is always 32 lowercase hex chars
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_safe_slug_null_byte_hashed():
    result = _safe_slug("user\x00name")
    assert "\x00" not in result


def test_safe_slug_single_dot_not_hashed():
    result = _safe_slug("2026-04.json")
    assert result == "2026-04_json"
    assert len(result) != 32  # not a hash


def test_safe_slug_max_length():
    result = _safe_slug("a" * 100)
    assert len(result) <= 64


def test_private_path_structure():
    key = WorkspaceKey(tenant_id="acme", user_id="alice", session_id="ses-1")
    path = WorkspacePathHelper.private("/data", key, "L2", "2026-04.json")
    path_str = path.as_posix()
    assert path_str.startswith("/data/workspaces/acme/users/alice/sessions/ses-1")
    assert "L2" in path_str


def test_team_path_uses_team_id_when_set():
    key = WorkspaceKey(tenant_id="acme", user_id="alice", session_id="ses-1", team_id="eng")
    path = WorkspacePathHelper.team("/data", key)
    path_str = path.as_posix()
    assert "teams/eng" in path_str


def test_team_path_falls_back_to_tenant_id():
    key = WorkspaceKey(tenant_id="acme", user_id="alice", session_id="ses-1")
    path = WorkspacePathHelper.team("/data", key)
    path_str = path.as_posix()
    assert "teams/acme" in path_str


def test_path_traversal_in_tenant_id_is_safe():
    key = WorkspaceKey(tenant_id="../evil", user_id="alice", session_id="s1")
    path = WorkspacePathHelper.private("/data", key)
    parts = Path(path).parts
    assert ".." not in parts


def test_parts_with_traversal_are_sanitized():
    key = WorkspaceKey(tenant_id="acme", user_id="alice", session_id="ses-1")
    path = WorkspacePathHelper.private("/data", key, "../escape")
    parts = Path(path).parts
    assert ".." not in parts


def test_empty_id_raises():
    with pytest.raises(ValueError):
        _safe_slug("")


def test_different_keys_produce_distinct_paths():
    key1 = WorkspaceKey(tenant_id="t1", user_id="alice", session_id="s1")
    key2 = WorkspaceKey(tenant_id="t1", user_id="bob", session_id="s1")
    assert WorkspacePathHelper.private("/data", key1) != WorkspacePathHelper.private("/data", key2)

from hi_agent.server.tenant_context import TenantContext
from hi_agent.server.workspace_path import WorkspaceKey


def test_tenant_context_has_session_id():
    ctx = TenantContext(tenant_id="t1", user_id="u1", session_id="s1")
    assert ctx.session_id == "s1"


def test_workspace_key_maps_correctly():
    ctx = TenantContext(tenant_id="t1", team_id="eng", user_id="u1", session_id="s1")
    key = ctx.workspace_key()
    assert key == WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1", team_id="eng")


def test_default_session_id_is_empty():
    ctx = TenantContext(tenant_id="t1", user_id="u1")
    assert ctx.session_id == ""

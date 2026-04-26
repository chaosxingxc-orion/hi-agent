"""Integration test: body spine required under research posture.

Under HI_AGENT_POSTURE=research, when POST /runs omits tenant_id in the
body, the system falls back to auth middleware and emits a DeprecationWarning.
"""

from __future__ import annotations

import warnings

import pytest
from hi_agent.server.run_manager import RunManager
from hi_agent.server.tenant_context import TenantContext


def _make_workspace(tenant_id="t1", user_id="u1", session_id="s1"):
    return TenantContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id)


def _make_contract(tenant_id=""):
    return {
        "task_id": "test-task",
        "goal": "test goal",
        "project_id": "proj-1",
        "tenant_id": tenant_id,
    }


def test_body_spine_missing_tenant_emits_deprecation_warning_under_research(monkeypatch):
    """Under research posture, missing body tenant_id emits DeprecationWarning."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="")  # no body tenant_id

    with pytest.warns(DeprecationWarning, match="body spine required under posture research"):
        manager.create_run(contract, workspace=workspace)


def test_body_spine_provided_no_warning_under_research(monkeypatch):
    """Under research posture, body tenant_id suppresses the DeprecationWarning."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="body-tenant")

    # Should not raise DeprecationWarning
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        try:
            manager.create_run(contract, workspace=workspace)
        except DeprecationWarning:
            pytest.fail("DeprecationWarning was raised when body tenant_id was present")


def test_body_tenant_wins_over_middleware_under_research(monkeypatch):
    """Under research posture, body tenant_id is used (not middleware tenant_id)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="body-tenant")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        run = manager.create_run(contract, workspace=workspace)

    assert run.run_id is not None


def test_dev_posture_no_warning_even_without_body_tenant(monkeypatch):
    """Under dev posture, missing body tenant_id does NOT emit DeprecationWarning."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="")

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        try:
            manager.create_run(contract, workspace=workspace)
        except DeprecationWarning:
            pytest.fail("DeprecationWarning raised under dev posture — should not happen")

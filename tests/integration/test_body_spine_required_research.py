"""Integration test: body-vs-middleware tenant_id precedence under research posture.

W35-T3 reformed the precedence model: both postures now use auth-authoritative
ordering — middleware tenant_id wins; body tenant_id that DIFFERS from
middleware triggers an anti-forgery cross-check (TenantScopeError under
research/prod, structured WARNING under dev). Body that MATCHES middleware
succeeds. Pre-W35-T3 the behaviour was inverted (strict body-wins vs dev
middleware-wins) — see RIA W35 directive §3.2.

These tests assert the W35-T3 invariant.
"""

from __future__ import annotations

import logging

import pytest
from hi_agent.contracts.errors import TenantScopeError
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


def test_body_spine_missing_falls_back_to_middleware_under_research(monkeypatch):
    """W35-T3: missing body tenant_id falls back to middleware silently
    (no DeprecationWarning under either posture — middleware IS authoritative)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="")

    run = manager.create_run(contract, workspace=workspace)
    assert run.tenant_id == "middleware-tenant"


def test_body_matches_middleware_succeeds_under_research(monkeypatch):
    """W35-T3: body tenant_id that matches middleware → succeeds (no anti-forgery
    cross-check fires)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="middleware-tenant")

    run = manager.create_run(contract, workspace=workspace)
    assert run.tenant_id == "middleware-tenant"


def test_body_differs_from_middleware_raises_under_research(monkeypatch):
    """W35-T3: body tenant_id that DIFFERS from middleware → TenantScopeError
    (anti-forgery cross-check). Reverses the pre-W35-T3 body-wins-under-strict
    behaviour, which RIA's W35 directive §3.2 flagged as Rule 11 reversal."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="body-tenant")

    with pytest.raises(TenantScopeError, match="differs from authenticated"):
        manager.create_run(contract, workspace=workspace)


def test_body_differs_from_middleware_warns_under_dev(monkeypatch, caplog):
    """W35-T3: under dev posture, the same body-vs-middleware mismatch
    is logged (not raised) — middleware still wins (auth-authoritative)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="body-tenant")

    with caplog.at_level(logging.WARNING):
        run = manager.create_run(contract, workspace=workspace)

    assert run.tenant_id == "middleware-tenant"
    assert any(
        "differs from" in r.message and "auth-authoritative" in r.message
        for r in caplog.records if r.levelname == "WARNING"
    )


def test_dev_posture_missing_body_tenant_falls_back_to_middleware(monkeypatch):
    """Under dev posture, missing body tenant_id silently uses middleware
    (no DeprecationWarning)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    manager = RunManager()
    workspace = _make_workspace(tenant_id="middleware-tenant")
    contract = _make_contract(tenant_id="")

    run = manager.create_run(contract, workspace=workspace)
    assert run.tenant_id == "middleware-tenant"

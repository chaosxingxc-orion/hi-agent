"""Strict-posture tenant_id enforcement in RunManager.create_run (T-12' fix).

W31, T-12' BLOCKER: RunManager.create_run had two fallback paths that landed
on a literal "default" tenant_id when neither middleware nor task_contract
carried one:

    # strict path (line 405)
    tenant_id = _middleware_tenant_id or task_contract_dict.get("tenant_id", "default")
    # dev path   (line 408)
    tenant_id = _middleware_tenant_id or _body_tenant_id or "default"

Both paths silently produced cross-tenant attribution. Under research/prod
this must raise TenantScopeError so the caller cannot create a run with no
tenant identity.

Behaviour now:
- research/prod posture + workspace=None and no body tenant_id → ValueError
  (already enforced by the workspace-required guard at line 388).
- research/prod posture + workspace with empty tenant_id and no body
  tenant_id → TenantScopeError (new T-12' enforcement).
- dev posture: keeps the legacy "default" fallback with an explicit WARNING
  log (back-compat).
"""

from __future__ import annotations

import logging

import pytest
from hi_agent.contracts.errors import TenantScopeError
from hi_agent.server.run_manager import RunManager
from hi_agent.server.run_store import SQLiteRunStore
from hi_agent.server.tenant_context import TenantContext

pytestmark = pytest.mark.integration


@pytest.fixture()
def run_store(tmp_path):
    return SQLiteRunStore(db_path=str(tmp_path / "runs-strict.sqlite3"))


@pytest.fixture()
def manager(run_store):
    return RunManager(max_concurrent=1, queue_size=4, run_store=run_store)


# ---------------------------------------------------------------------------
# Strict posture: raises rather than coercing to "default"
# ---------------------------------------------------------------------------


class TestStrictPostureForbidsDefaultFallback:
    def test_research_posture_with_empty_workspace_raises(
        self, monkeypatch, manager
    ):
        """workspace.tenant_id="" under research → TenantScopeError, NOT "default"."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        # Simulate auth middleware that produced a context with empty tenant_id
        # (i.e. silent downgrade we are forbidding).
        ctx = TenantContext(tenant_id="", user_id="u1", session_id="s1")
        with pytest.raises(TenantScopeError):
            manager.create_run(
                {"goal": "x", "task_id": "t-strict-default-1"},
                workspace=ctx,
            )

    def test_prod_posture_with_empty_workspace_raises(
        self, monkeypatch, manager
    ):
        """workspace.tenant_id="" under prod → TenantScopeError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        ctx = TenantContext(tenant_id="", user_id="u1", session_id="s1")
        with pytest.raises(TenantScopeError):
            manager.create_run(
                {"goal": "x", "task_id": "t-strict-default-2"},
                workspace=ctx,
            )

    def test_research_posture_with_workspace_uses_workspace_tenant(
        self, monkeypatch, manager, run_store
    ):
        """Sanity: strict posture with valid workspace tenant succeeds."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx = TenantContext(tenant_id="tenant-A", user_id="u1", session_id="s1")
        run = manager.create_run(
            {"goal": "x", "task_id": "t-strict-default-3"},
            workspace=ctx,
        )
        record = run_store.get(run.run_id)
        assert record is not None
        assert record.tenant_id == "tenant-A"

    def test_research_posture_body_tenant_id_used(
        self, monkeypatch, manager, run_store
    ):
        """Under strict, explicit body tenant_id wins over middleware (existing behaviour)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx = TenantContext(tenant_id="tenant-A", user_id="u1", session_id="s1")
        run = manager.create_run(
            {
                "goal": "x",
                "task_id": "t-strict-default-4",
                "tenant_id": "tenant-B",
            },
            workspace=ctx,
        )
        record = run_store.get(run.run_id)
        assert record is not None
        # body wins under strict
        assert record.tenant_id == "tenant-B"


# ---------------------------------------------------------------------------
# Dev posture: keeps legacy "default" fallback with WARNING
# ---------------------------------------------------------------------------


class TestDevPostureKeepsDefaultFallback:
    def test_dev_posture_no_workspace_uses_default(
        self, monkeypatch, manager, run_store, caplog
    ):
        """Dev + workspace=None + no body tenant → tenant_id='default' with WARNING."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        with caplog.at_level(logging.WARNING):
            run = manager.create_run(
                {"goal": "x", "task_id": "t-dev-default-1"},
                workspace=None,
            )
        record = run_store.get(run.run_id)
        assert record is not None
        # Note: tenant_id is the resolved value used in the DB row; under dev
        # workspace=None means the run lands on the legacy "default" bucket.
        assert record.tenant_id == "default"
        # WARNING log mentioning the default fallback (not silent).
        warning_msgs = [
            rec.message for rec in caplog.records if rec.levelname == "WARNING"
        ]
        assert any(
            "tenant_id" in msg.lower() and "default" in msg.lower()
            for msg in warning_msgs
        ), (
            f"Expected WARNING about tenant_id default fallback; "
            f"got: {warning_msgs}"
        )

    def test_dev_posture_with_workspace_uses_workspace(
        self, monkeypatch, manager, run_store
    ):
        """Dev + valid workspace tenant → that tenant (no fallback)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        ctx = TenantContext(tenant_id="tenant-X", user_id="u1", session_id="s1")
        run = manager.create_run(
            {"goal": "x", "task_id": "t-dev-default-2"},
            workspace=ctx,
        )
        record = run_store.get(run.run_id)
        assert record is not None
        assert record.tenant_id == "tenant-X"

"""Strict-posture tenant_id enforcement in RunManager.create_run.

Originally landed under W31 (T-12' BLOCKER). W35-T3 reformed the
precedence model from "body wins under strict, middleware wins under
dev" (an INVERTED Rule 11 reversal where strict was MORE permissive
than dev) to a unified auth-authoritative model: middleware tenant_id
always wins; body tenant_id is permitted only when middleware is
absent. A body tenant_id that differs from middleware is treated as a
forgery attempt — TenantScopeError under strict, structured warning
under dev.

Spine validation at the TenantContext layer (W35-T1) further closes
the gap: under research/prod it is no longer possible to even CONSTRUCT
a TenantContext with empty tenant_id, so the "empty workspace" test
shape now lives at the contract layer rather than the run-manager
layer.

Behaviour now:
- research/prod posture + workspace=None → ValueError (workspace-required guard).
- research/prod posture + TenantContext(tenant_id="") → SpineCompletenessError
  raised at TenantContext construction (W35-T1).
- research/prod posture + workspace with valid tenant_id and no body
  tenant_id → tenant_id = workspace.tenant_id.
- research/prod posture + workspace=A and body=B (mismatch) → TenantScopeError
  (W35-T3 anti-forgery cross-check).
- dev posture: keeps the legacy "default" fallback with an explicit WARNING
  log (back-compat) when both middleware and body are empty.
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
    def test_research_posture_empty_tenant_context_raises_at_construction(
        self, monkeypatch
    ):
        """W35-T1: TenantContext with empty tenant_id raises under research."""
        from hi_agent.contracts.reasoning import SpineCompletenessError

        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        with pytest.raises(SpineCompletenessError):
            TenantContext(tenant_id="", user_id="u1", session_id="s1")

    def test_prod_posture_empty_tenant_context_raises_at_construction(
        self, monkeypatch
    ):
        """W35-T1: TenantContext with empty tenant_id raises under prod."""
        from hi_agent.contracts.reasoning import SpineCompletenessError

        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        with pytest.raises(SpineCompletenessError):
            TenantContext(tenant_id="", user_id="u1", session_id="s1")

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

    def test_research_posture_body_tenant_id_mismatch_raises(
        self, monkeypatch, manager
    ):
        """W35-T3: under strict, body tenant_id that differs from middleware
        is treated as a forgery attempt — TenantScopeError raised.

        Reverses the pre-W35-T3 behaviour where body silently overrode
        middleware (Rule 11 reversal — strict was more permissive than dev).
        """
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx = TenantContext(tenant_id="tenant-A", user_id="u1", session_id="s1")
        with pytest.raises(TenantScopeError):
            manager.create_run(
                {
                    "goal": "x",
                    "task_id": "t-strict-default-4",
                    "tenant_id": "tenant-B",  # differs from middleware
                },
                workspace=ctx,
            )

    def test_research_posture_body_tenant_id_match_succeeds(
        self, monkeypatch, manager, run_store
    ):
        """W35-T3: under strict, body tenant_id that MATCHES middleware
        succeeds and uses the middleware (auth-authoritative)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx = TenantContext(tenant_id="tenant-A", user_id="u1", session_id="s1")
        run = manager.create_run(
            {
                "goal": "x",
                "task_id": "t-strict-default-5",
                "tenant_id": "tenant-A",  # matches middleware
            },
            workspace=ctx,
        )
        record = run_store.get(run.run_id)
        assert record is not None
        assert record.tenant_id == "tenant-A"


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

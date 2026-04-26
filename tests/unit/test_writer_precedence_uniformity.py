"""Tests that explicit kwargs win over exec_ctx for all writers with exec_ctx support.

Layer 1 — Unit tests; no external network; mocks only where noted.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _dev_posture(monkeypatch):
    """Force dev posture so ArtifactRegistry can be constructed."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


def _make_ctx(**overrides):
    from hi_agent.context.run_execution_context import RunExecutionContext

    defaults = dict(
        tenant_id="ctx-tenant",
        user_id="ctx-user",
        session_id="ctx-session",
        project_id="ctx-project",
        profile_id="ctx-profile",
        run_id="ctx-run",
        parent_run_id="",
        stage_id="",
        capability_name="",
        request_id="",
    )
    defaults.update(overrides)
    return RunExecutionContext(**defaults)


# ---------------------------------------------------------------------------
# op_store — LongRunningOpStore.create()
# ---------------------------------------------------------------------------


def test_op_store_explicit_tenant_id_wins(tmp_path):
    """op_store.create(): explicit tenant_id kwarg wins over exec_ctx.tenant_id."""
    from hi_agent.operations.op_store import LongRunningOpStore

    store = LongRunningOpStore(db_path=tmp_path / "test.db")
    ctx = _make_ctx(tenant_id="ctx-tenant")

    op = store.create(
        op_id="op-001",
        backend="test",
        external_id="ext-001",
        submitted_at=0.0,
        exec_ctx=ctx,
        tenant_id="explicit-tenant",
    )
    assert op.tenant_id == "explicit-tenant", (
        f"kwargs-wins expected 'explicit-tenant', got '{op.tenant_id}'"
    )


def test_op_store_explicit_run_id_wins(tmp_path):
    """op_store.create(): explicit run_id kwarg wins over exec_ctx.run_id."""
    from hi_agent.operations.op_store import LongRunningOpStore

    store = LongRunningOpStore(db_path=tmp_path / "test.db")
    ctx = _make_ctx(run_id="ctx-run")

    op = store.create(
        op_id="op-002",
        backend="test",
        external_id="ext-002",
        submitted_at=0.0,
        exec_ctx=ctx,
        run_id="explicit-run",
    )
    assert op.run_id == "explicit-run", (
        f"kwargs-wins expected 'explicit-run', got '{op.run_id}'"
    )


def test_op_store_explicit_project_id_wins(tmp_path):
    """op_store.create(): explicit project_id kwarg wins over exec_ctx.project_id."""
    from hi_agent.operations.op_store import LongRunningOpStore

    store = LongRunningOpStore(db_path=tmp_path / "test.db")
    ctx = _make_ctx(project_id="ctx-project")

    op = store.create(
        op_id="op-003",
        backend="test",
        external_id="ext-003",
        submitted_at=0.0,
        exec_ctx=ctx,
        project_id="explicit-project",
    )
    assert op.project_id == "explicit-project", (
        f"kwargs-wins expected 'explicit-project', got '{op.project_id}'"
    )


def test_op_store_exec_ctx_fills_empty_fields(tmp_path):
    """op_store.create(): exec_ctx fills fields the caller did not specify."""
    from hi_agent.operations.op_store import LongRunningOpStore

    store = LongRunningOpStore(db_path=tmp_path / "test.db")
    ctx = _make_ctx(tenant_id="ctx-tenant", run_id="ctx-run", project_id="ctx-proj")

    op = store.create(
        op_id="op-004",
        backend="test",
        external_id="ext-004",
        submitted_at=0.0,
        exec_ctx=ctx,
        # no spine kwargs supplied — exec_ctx should fill all three
    )
    assert op.tenant_id == "ctx-tenant"
    assert op.run_id == "ctx-run"
    assert op.project_id == "ctx-proj"


def test_op_store_persisted_record_reflects_kwargs_win(tmp_path):
    """The row written to SQLite uses kwargs-wins values, not exec_ctx values."""
    from hi_agent.operations.op_store import LongRunningOpStore

    store = LongRunningOpStore(db_path=tmp_path / "test.db")
    ctx = _make_ctx(tenant_id="ctx-tenant", run_id="ctx-run", project_id="ctx-proj")

    store.create(
        op_id="op-005",
        backend="test",
        external_id="ext-005",
        submitted_at=0.0,
        exec_ctx=ctx,
        tenant_id="explicit-tenant",
        run_id="explicit-run",
        project_id="explicit-proj",
    )
    fetched = store.get("op-005")
    assert fetched is not None
    assert fetched.tenant_id == "explicit-tenant"
    assert fetched.run_id == "explicit-run"
    assert fetched.project_id == "explicit-proj"


# ---------------------------------------------------------------------------
# ArtifactRegistry — already uses kwargs-wins; confirm it still does
# ---------------------------------------------------------------------------


def test_artifact_registry_explicit_tenant_id_wins():
    """ArtifactRegistry.create(): explicit tenant_id kwarg wins over exec_ctx."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    registry = ArtifactRegistry()
    ctx = _make_ctx(tenant_id="ctx-tenant", run_id="ctx-run")

    artifact = registry.create(
        exec_ctx=ctx,
        artifact_type="test",
        tenant_id="explicit-tenant",
    )
    assert artifact.tenant_id == "explicit-tenant", (
        f"kwargs-wins expected 'explicit-tenant', got '{artifact.tenant_id}'"
    )


def test_artifact_registry_exec_ctx_fills_unspecified_fields():
    """ArtifactRegistry.create(): exec_ctx fills fields the caller did not specify."""
    from hi_agent.artifacts.registry import ArtifactRegistry

    registry = ArtifactRegistry()
    ctx = _make_ctx(tenant_id="ctx-tenant", run_id="ctx-run", project_id="ctx-proj")

    artifact = registry.create(exec_ctx=ctx, artifact_type="test")
    assert artifact.tenant_id == "ctx-tenant"
    assert artifact.run_id == "ctx-run"
    assert artifact.project_id == "ctx-proj"

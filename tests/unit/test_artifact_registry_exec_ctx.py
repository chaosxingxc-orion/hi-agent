"""Unit tests for ArtifactRegistry.create with exec_ctx.

Layer 1 — Unit tests; in-memory registry (no external mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext


@pytest.fixture(autouse=True)
def dev_posture(monkeypatch):
    """Force dev posture so ArtifactRegistry can be constructed in tests."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


@pytest.fixture()
def registry():
    from hi_agent.artifacts.registry import ArtifactRegistry
    return ArtifactRegistry()


class TestCreateWithExecCtx:
    def test_exec_ctx_run_id_and_project_id_stored(self, registry):
        """exec_ctx.run_id and exec_ctx.project_id are set on the created Artifact."""
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
            run_id="run-001",
        )
        artifact = registry.create(exec_ctx=ctx, artifact_type="test")
        assert artifact.run_id == "run-001"
        assert artifact.project_id == "p1"
        assert artifact.tenant_id == "t1"
        assert artifact.user_id == "u1"
        assert artifact.session_id == "s1"

    def test_exec_ctx_none_uses_explicit_kwargs(self, registry):
        """When exec_ctx is None, kwargs are forwarded directly to Artifact."""
        artifact = registry.create(
            exec_ctx=None,
            artifact_type="test",
            run_id="run-explicit",
            project_id="p-explicit",
        )
        assert artifact.run_id == "run-explicit"
        assert artifact.project_id == "p-explicit"

    def test_explicit_kwargs_take_precedence_over_exec_ctx(self, registry):
        """kwargs already set by the caller are NOT overwritten by exec_ctx."""
        ctx = RunExecutionContext(
            run_id="run-from-ctx",
            project_id="p-from-ctx",
        )
        # run_id and project_id explicitly set in kwargs → they win over ctx defaults
        artifact = registry.create(
            exec_ctx=ctx,
            artifact_type="test",
            run_id="run-explicit",
            project_id="p-explicit",
        )
        assert artifact.run_id == "run-explicit"
        assert artifact.project_id == "p-explicit"

    def test_artifact_stored_in_registry(self, registry):
        """Created artifact is immediately retrievable from the registry."""
        ctx = RunExecutionContext(
            tenant_id="t1",
            run_id="run-stored",
        )
        artifact = registry.create(exec_ctx=ctx)
        retrieved = registry.get(artifact.artifact_id)
        assert retrieved is not None
        assert retrieved.artifact_id == artifact.artifact_id
        assert retrieved.run_id == "run-stored"

    def test_create_without_exec_ctx_backward_compat(self, registry):
        """Existing callers that pass no exec_ctx continue to work."""
        artifact = registry.create(artifact_type="test", producer_action_id="act-001")
        assert artifact.artifact_type == "test"
        assert artifact.producer_action_id == "act-001"

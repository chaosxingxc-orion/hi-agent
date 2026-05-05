"""W34-F.2 / B-W34-1: RunExecutionContext.from_managed_run lineage population.

Closes the W33 carryover F.2: ``from_managed_run`` previously hardcoded
empty strings for ``parent_run_id`` / ``attempt_id`` / ``phase_id``. The fix
threads them from the live ManagedRun spine.

Layer: unit (Rule 4 Layer 1; constructor + value-copy only, no IO).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.context.run_execution_context import RunExecutionContext


def _stub_managed_run(
    *,
    run_id: str = "run-abc",
    tenant_id: str = "tenant-A",
    parent_run_id: str = "",
    attempt_id: str = "",
    phase_id: str = "",
    profile_id: str = "",
) -> MagicMock:
    """Build a MagicMock standing in for ManagedRun.

    MagicMock is appropriate here per Rule 4 Layer 1: this is a pure
    constructor-copy test for ``RunExecutionContext.from_managed_run``;
    ManagedRun itself is not the subject under test.
    """
    run = MagicMock()
    run.run_id = run_id
    run.tenant_id = tenant_id
    run.user_id = "user-1"
    run.session_id = "sess-1"
    run.project_id = "proj-1"
    run.parent_run_id = parent_run_id
    run.attempt_id = attempt_id
    run.phase_id = phase_id
    run.profile_id = profile_id
    run.task_contract = {"project_id": "proj-1"}
    run.current_stage = "S2"
    return run


def test_from_managed_run_copies_parent_run_id() -> None:
    """parent_run_id from ManagedRun must surface on the context."""
    run = _stub_managed_run(parent_run_id="run-parent-xyz")
    ctx = RunExecutionContext.from_managed_run(run)
    assert ctx.parent_run_id == "run-parent-xyz"


def test_from_managed_run_copies_attempt_id() -> None:
    """attempt_id from ManagedRun must surface on the context."""
    run = _stub_managed_run(attempt_id="attempt-uuid-2")
    ctx = RunExecutionContext.from_managed_run(run)
    assert ctx.attempt_id == "attempt-uuid-2"


def test_from_managed_run_copies_phase_id() -> None:
    """phase_id from ManagedRun must surface on the context."""
    run = _stub_managed_run(phase_id="execute")
    ctx = RunExecutionContext.from_managed_run(run)
    assert ctx.phase_id == "execute"


def test_from_managed_run_copies_profile_id() -> None:
    """profile_id from ManagedRun must surface on the context."""
    run = _stub_managed_run(profile_id="default-research")
    ctx = RunExecutionContext.from_managed_run(run)
    assert ctx.profile_id == "default-research"


def test_from_managed_run_threads_full_lineage_chain() -> None:
    """Full lineage block (parent / attempt / phase) populates simultaneously."""
    run = _stub_managed_run(
        parent_run_id="run-parent",
        attempt_id="attempt-2",
        phase_id="finalize",
    )
    ctx = RunExecutionContext.from_managed_run(run)
    assert ctx.parent_run_id == "run-parent"
    assert ctx.attempt_id == "attempt-2"
    assert ctx.phase_id == "finalize"
    # Sanity: tenant/run identity also surfaces.
    assert ctx.tenant_id == "tenant-A"
    assert ctx.run_id == "run-abc"


def test_from_managed_run_root_run_keeps_empty_parent() -> None:
    """Root runs (no parent) construct cleanly with parent_run_id=''."""
    run = _stub_managed_run(parent_run_id="", attempt_id="attempt-1", phase_id="intake")
    ctx = RunExecutionContext.from_managed_run(run)
    assert ctx.parent_run_id == ""  # legitimate root-run shape
    assert ctx.attempt_id == "attempt-1"


def test_with_attempt_records_parent_chain() -> None:
    """``with_attempt`` mints a new attempt and chains parent_run_id back."""
    base = RunExecutionContext(
        tenant_id="tenant-A",
        run_id="run-abc",
        attempt_id="attempt-1",
        parent_run_id="",
    )
    next_ctx = base.with_attempt("attempt-2")
    assert next_ctx.attempt_id == "attempt-2"
    # Default linkage: parent_run_id falls back to the source run_id, so the
    # lineage chain is reconstructible from the persisted records alone.
    assert next_ctx.parent_run_id == "run-abc"


def test_to_lineage_kwargs_returns_lineage_block() -> None:
    """``to_lineage_kwargs`` returns exactly the three lineage fields."""
    ctx = RunExecutionContext(
        tenant_id="tenant-A",
        run_id="run-abc",
        parent_run_id="run-parent",
        attempt_id="attempt-3",
        phase_id="execute",
    )
    kwargs = ctx.to_lineage_kwargs()
    assert kwargs == {
        "parent_run_id": "run-parent",
        "attempt_id": "attempt-3",
        "phase_id": "execute",
    }


def test_to_spine_kwargs_full_includes_lineage() -> None:
    """``to_spine_kwargs_full`` covers all 12 identity fields including lineage."""
    ctx = RunExecutionContext(
        tenant_id="tenant-A",
        run_id="run-abc",
        parent_run_id="run-parent",
        attempt_id="attempt-3",
        phase_id="execute",
    )
    full = ctx.to_spine_kwargs_full()
    assert full["parent_run_id"] == "run-parent"
    assert full["attempt_id"] == "attempt-3"
    assert full["phase_id"] == "execute"
    assert full["tenant_id"] == "tenant-A"
    assert full["run_id"] == "run-abc"

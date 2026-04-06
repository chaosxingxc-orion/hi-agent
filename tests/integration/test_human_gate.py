"""Integration flow tests for in-memory human gate management."""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import GateStatus, InMemoryGateAPI, resolve_gate_api
from hi_agent.management.gate_context import build_gate_context


def test_human_gate_create_list_resolve_flow() -> None:
    """Gate should progress from pending to approved via explicit resolution."""
    api = InMemoryGateAPI(now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-int-1",
        run_id="run-int-1",
        stage_id="S3_build",
        branch_id="branch-1",
        submitter="planner",
        now_fn=lambda: 100.0,
    )
    created = api.create_gate(context=context)

    pending = api.list_pending()
    assert len(pending) == 1
    assert pending[0].context.gate_ref == "gate-int-1"
    assert created.status is GateStatus.PENDING

    resolved = resolve_gate_api(
        api=api,
        gate_ref="gate-int-1",
        action="approve",
        approver="reviewer",
        comment="looks good",
    )
    assert resolved.status is GateStatus.APPROVED
    assert api.list_pending() == []


def test_human_gate_rejects_duplicate_resolution() -> None:
    """Duplicate resolve calls should fail with a clear validation error."""
    api = InMemoryGateAPI(now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-int-2",
        run_id="run-int-2",
        stage_id="S4_synthesize",
        branch_id="branch-2",
        submitter="author",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)
    resolve_gate_api(
        api=api,
        gate_ref="gate-int-2",
        action="reject",
        approver="reviewer",
    )

    with pytest.raises(ValueError, match="already resolved"):
        resolve_gate_api(
            api=api,
            gate_ref="gate-int-2",
            action="approve",
            approver="reviewer-2",
        )


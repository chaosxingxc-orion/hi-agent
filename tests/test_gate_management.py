"""Unit tests for human-gate management helpers."""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import (
    GateStatus,
    InMemoryGateAPI,
    resolve_gate_api,
)
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_timeout import GateTimeoutPolicy, resolve_gate_timeout


def test_build_gate_context_validates_required_fields() -> None:
    """Builder should reject empty required identifiers."""
    with pytest.raises(ValueError):
        build_gate_context(
            gate_ref="",
            run_id="run-1",
            stage_id="S1_understand",
            branch_id="b-1",
            submitter="planner",
        )


def test_resolve_gate_timeout_respects_policy() -> None:
    """Timeout helper should map policy to deterministic action."""
    result = resolve_gate_timeout(
        opened_at=100.0,
        timeout_seconds=10.0,
        policy=GateTimeoutPolicy.REJECT,
        now_fn=lambda: 111.0,
    )
    assert result.timed_out is True
    assert result.action == "reject"
    assert result.reason == "timeout_auto_reject"


def test_gate_api_enforces_soc_when_submitter_approves() -> None:
    """Submitter approval should be forbidden when SoC is enabled."""
    api = InMemoryGateAPI(enforce_separation_of_concerns=True, now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-1",
        run_id="run-1",
        stage_id="S1_understand",
        branch_id="b-1",
        submitter="alice",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)

    with pytest.raises(PermissionError):
        resolve_gate_api(
            api=api,
            gate_ref="gate-1",
            action="approve",
            approver="alice",
            comment="self-approve",
        )


def test_gate_api_rejects_double_resolution() -> None:
    """Gates should be resolved at most once."""
    api = InMemoryGateAPI(now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-2",
        run_id="run-2",
        stage_id="S2_gather",
        branch_id="b-2",
        submitter="author",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)

    first = resolve_gate_api(api=api, gate_ref="gate-2", action="reject", approver="reviewer")
    assert first.status is GateStatus.REJECTED

    with pytest.raises(ValueError):
        resolve_gate_api(api=api, gate_ref="gate-2", action="approve", approver="ops")


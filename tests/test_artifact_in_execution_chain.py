"""Tests for D4 fix: artifact_ids propagated through the execution chain.

Verifies:
1. StageSummary has artifact_ids field (D4-1)
2. _invoke_via_harness() includes artifact_ids in the return dict (D4-2)
3. ActionSpec accepts upstream_artifact_ids (D5 pre-condition)
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any
from unittest.mock import MagicMock

import pytest

from hi_agent.contracts.memory import StageSummary
from hi_agent.harness.contracts import ActionResult, ActionSpec, ActionState
from hi_agent.harness.executor import HarnessExecutor


# ---------------------------------------------------------------------------
# D4-1: StageSummary has artifact_ids field
# ---------------------------------------------------------------------------


class TestStageSummaryArtifactIds:
    """StageSummary must have an artifact_ids field (default empty list)."""

    def test_stage_summary_has_artifact_ids_field(self) -> None:
        """StageSummary dataclass must declare artifact_ids."""
        field_names = {f.name for f in fields(StageSummary)}
        assert "artifact_ids" in field_names, (
            "StageSummary must have an artifact_ids field"
        )

    def test_stage_summary_artifact_ids_defaults_to_empty_list(self) -> None:
        """Default value for artifact_ids must be an empty list."""
        summary = StageSummary(stage_id="S1", stage_name="understand")
        assert summary.artifact_ids == []

    def test_stage_summary_accepts_artifact_ids(self) -> None:
        """StageSummary can be constructed with artifact_ids."""
        ids = ["abc123", "def456"]
        summary = StageSummary(
            stage_id="S1",
            stage_name="understand",
            artifact_ids=ids,
        )
        assert summary.artifact_ids == ids

    def test_stage_summary_artifact_ids_are_mutable(self) -> None:
        """artifact_ids list must be a fresh list per instance (not shared)."""
        s1 = StageSummary(stage_id="S1", stage_name="A")
        s2 = StageSummary(stage_id="S2", stage_name="B")
        s1.artifact_ids.append("id-1")
        assert s2.artifact_ids == [], (
            "artifact_ids must not be a shared default mutable"
        )


# ---------------------------------------------------------------------------
# D4-2: _invoke_via_harness includes artifact_ids in return dict
# ---------------------------------------------------------------------------


def _make_mock_harness_executor(artifact_ids: list[str] | None = None) -> Any:
    """Build a mock HarnessExecutor that returns a fake ActionResult."""
    mock_executor = MagicMock(spec=HarnessExecutor)
    mock_result = ActionResult(
        action_id="action-001",
        state=ActionState.SUCCEEDED,
        output={"score": 0.8, "data": "test"},
        evidence_ref="ev-action-001-abc123",
        artifact_ids=artifact_ids or ["art-001", "art-002"],
    )
    mock_executor.execute.return_value = mock_result
    return mock_executor


class TestInvokeViaHarnessArtifactIds:
    """_invoke_via_harness must include artifact_ids in its return dict."""

    def test_harness_result_includes_artifact_ids(self) -> None:
        """The dict returned by _invoke_via_harness must have artifact_ids key."""
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor
        from tests.helpers.kernel_adapter_fixture import MockKernel

        kernel = MockKernel(strict_mode=True)
        contract = TaskContract(task_id="test-aid-001", goal="artifact ids test")

        harness = _make_mock_harness_executor(["art-001", "art-002"])
        executor = RunExecutor(contract, kernel, invoker=None)
        executor.harness_executor = harness
        executor.run_id = "run-0001"

        # Build a minimal proposal and payload
        from hi_agent.route_engine.rule_engine import BranchProposal
        proposal = BranchProposal(
            branch_id="branch-abc",
            rationale="test",
            action_kind="test_action",
        )
        payload = {
            "run_id": "run-0001",
            "stage_id": "S1",
            "branch_id": "branch-abc",
            "seq": 0,
            "attempt": 1,
            "action_kind": "test_action",
            "should_fail": False,
            "upstream_artifact_ids": [],
        }

        result = executor._invoke_via_harness(proposal, payload)

        assert "artifact_ids" in result, (
            "_invoke_via_harness must include artifact_ids in its return dict"
        )
        assert result["artifact_ids"] == ["art-001", "art-002"]

    def test_harness_result_artifact_ids_defaults_to_empty_on_failure(self) -> None:
        """When harness returns a failed result, artifact_ids should still be present."""
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor
        from tests.helpers.kernel_adapter_fixture import MockKernel

        kernel = MockKernel(strict_mode=True)
        contract = TaskContract(task_id="test-aid-002", goal="artifact ids failure test")

        mock_executor = MagicMock(spec=HarnessExecutor)
        mock_result = ActionResult(
            action_id="action-002",
            state=ActionState.FAILED,
            error_code="harness_denied",
            artifact_ids=[],
        )
        mock_executor.execute.return_value = mock_result

        executor = RunExecutor(contract, kernel, invoker=None)
        executor.harness_executor = mock_executor
        executor.run_id = "run-0001"

        from hi_agent.route_engine.rule_engine import BranchProposal
        proposal = BranchProposal(
            branch_id="branch-xyz",
            rationale="test",
            action_kind="test_action",
        )
        payload = {
            "run_id": "run-0001",
            "stage_id": "S1",
            "branch_id": "branch-xyz",
            "seq": 0,
            "attempt": 1,
            "action_kind": "test_action",
            "should_fail": False,
            "upstream_artifact_ids": [],
        }

        result = executor._invoke_via_harness(proposal, payload)

        assert "artifact_ids" in result
        assert isinstance(result["artifact_ids"], list)


# ---------------------------------------------------------------------------
# D5: ActionSpec accepts upstream_artifact_ids
# ---------------------------------------------------------------------------


class TestActionSpecUpstreamArtifactIds:
    """ActionSpec must accept upstream_artifact_ids for lineage tracking."""

    def test_action_spec_has_upstream_artifact_ids_field(self) -> None:
        """ActionSpec must declare upstream_artifact_ids."""
        field_names = {f.name for f in fields(ActionSpec)}
        assert "upstream_artifact_ids" in field_names

    def test_action_spec_upstream_artifact_ids_defaults_to_empty(self) -> None:
        """Default upstream_artifact_ids must be empty list."""
        spec = ActionSpec(
            action_id="a1",
            action_type="read",
            capability_name="test",
            payload={},
        )
        assert spec.upstream_artifact_ids == []

    def test_action_spec_accepts_upstream_ids(self) -> None:
        """ActionSpec can be constructed with upstream_artifact_ids."""
        spec = ActionSpec(
            action_id="a1",
            action_type="read",
            capability_name="test",
            payload={},
            upstream_artifact_ids=["parent-001"],
        )
        assert spec.upstream_artifact_ids == ["parent-001"]

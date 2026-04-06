"""Tests for runner integrations: Evolve, Harness, and Human Gate auto-triggers.

Validates that RunExecutor correctly wires:
- EvolveEngine postmortem after run completion (success and failure)
- HarnessExecutor-governed action execution
- Human Gate auto-triggers based on architecture rules
- Backward compatibility when all new params are None
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from hi_agent.contracts import (
    NodeState,
    StageState,
    TaskBudget,
    TaskContract,
)
from hi_agent.evolve.contracts import EvolveResult, RunPostmortem
from hi_agent.harness.contracts import ActionResult, ActionSpec, ActionState
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.mock_kernel import MockKernel


def _make_contract(
    task_id: str = "test-int-001",
    goal: str = "integration test",
    **kwargs: object,
) -> TaskContract:
    """Helper to create task contracts for tests."""
    return TaskContract(task_id=task_id, goal=goal, **kwargs)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class FakeEvolveEngine:
    """Minimal fake that records on_run_completed calls."""

    def __init__(self) -> None:
        self.postmortems: list[RunPostmortem] = []

    def on_run_completed(self, postmortem: RunPostmortem) -> EvolveResult:
        self.postmortems.append(postmortem)
        from hi_agent.evolve.contracts import EvolveMetrics

        return EvolveResult(
            trigger="per_run_postmortem",
            change_scope="all",
            changes=[],
            metrics=EvolveMetrics(runs_analyzed=1),
            run_ids_analyzed=[postmortem.run_id],
            timestamp="2026-04-07T00:00:00Z",
        )


class FakeHarnessExecutor:
    """Minimal fake that records execute calls and returns success."""

    def __init__(
        self,
        *,
        succeed: bool = True,
        output: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[ActionSpec] = []
        self._succeed = succeed
        self._output = output or {"score": 1.0}

    def execute(self, spec: ActionSpec) -> ActionResult:
        self.calls.append(spec)
        if self._succeed:
            return ActionResult(
                action_id=spec.action_id,
                state=ActionState.SUCCEEDED,
                output=self._output,
                evidence_ref=f"ev-{spec.action_id}",
            )
        return ActionResult(
            action_id=spec.action_id,
            state=ActionState.FAILED,
            error_code="harness_execution_failed",
            error_message="Fake failure",
        )


# ===========================================================================
# 1. Evolve postmortem trigger
# ===========================================================================


class TestEvolvePostmortemOnSuccess:
    """EvolveEngine.on_run_completed called after a successful run."""

    def test_postmortem_triggered_after_success(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        evolve = FakeEvolveEngine()
        executor = RunExecutor(contract, kernel, evolve_engine=evolve)

        result = executor.execute()

        assert result == "completed"
        assert len(evolve.postmortems) == 1
        pm = evolve.postmortems[0]
        assert pm.outcome == "completed"
        assert pm.task_id == "test-int-001"
        assert pm.run_id == executor.run_id
        assert pm.total_actions == executor.action_seq

    def test_postmortem_stages_completed(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        evolve = FakeEvolveEngine()
        executor = RunExecutor(contract, kernel, evolve_engine=evolve)

        executor.execute()

        pm = evolve.postmortems[0]
        assert len(pm.stages_completed) > 0
        assert len(pm.stages_failed) == 0


class TestEvolvePostmortemOnFailure:
    """EvolveEngine.on_run_completed called after a failed run."""

    def test_postmortem_triggered_after_failure(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(
            constraints=["fail_action:analyze_goal"]
        )
        evolve = FakeEvolveEngine()
        executor = RunExecutor(contract, kernel, evolve_engine=evolve)

        result = executor.execute()

        assert result == "failed"
        assert len(evolve.postmortems) == 1
        pm = evolve.postmortems[0]
        assert pm.outcome == "failed"
        assert len(pm.stages_failed) >= 1


class TestEvolveNotProvided:
    """No evolve engine provided -- no postmortem, no crash."""

    def test_no_evolve_no_crash(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, evolve_engine=None)

        result = executor.execute()

        assert result == "completed"


# ===========================================================================
# 2. Harness executor wrapping
# ===========================================================================


class TestHarnessExecutorUsed:
    """When harness_executor is provided, actions route through it."""

    def test_harness_receives_action_specs(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        harness = FakeHarnessExecutor(succeed=True)
        executor = RunExecutor(
            contract, kernel, harness_executor=harness
        )

        result = executor.execute()

        assert result == "completed"
        # At least one action should have gone through the harness
        assert len(harness.calls) > 0
        # Each call should be an ActionSpec
        for spec in harness.calls:
            assert isinstance(spec, ActionSpec)

    def test_harness_failure_propagates(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        harness = FakeHarnessExecutor(succeed=False)
        executor = RunExecutor(
            contract, kernel, harness_executor=harness
        )

        result = executor.execute()

        # With all actions failing, the run should fail
        assert result == "failed"


class TestHarnessNotProvided:
    """No harness executor -- direct capability invocation as before."""

    def test_direct_invocation_without_harness(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(
            contract, kernel, harness_executor=None
        )

        result = executor.execute()

        assert result == "completed"


# ===========================================================================
# 3. Human Gate auto-triggers
# ===========================================================================


class TestHumanGateContradictoryEvidence:
    """Gate A triggered on contradictory_evidence failure code."""

    def test_gate_a_on_contradictory_evidence(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel)
        # Manually trigger execute to get a valid run_id
        executor._run_id = kernel.start_run(contract.task_id)

        # Directly test the gate trigger method
        executor._check_human_gate_triggers(
            "S1_understand",
            {"failure_code": "contradictory_evidence"},
            failure_code="contradictory_evidence",
        )

        assert len(kernel.gates) == 1
        gate = list(kernel.gates.values())[0]
        assert gate["gate_type"] == "contract_correction"
        assert gate["status"] == "pending"


class TestHumanGateBudgetCrisis:
    """Gate B triggered when budget >80% used and no viable branch."""

    def test_gate_b_on_budget_crisis(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(
            budget=TaskBudget(max_actions=10)
        )
        executor = RunExecutor(contract, kernel)
        executor._run_id = kernel.start_run(contract.task_id)
        # Simulate 9 actions used (90% of 10)
        executor.action_seq = 9

        executor._check_human_gate_triggers(
            "S2_gather",
            {},
            failure_code=None,
        )

        assert len(kernel.gates) == 1
        gate = list(kernel.gates.values())[0]
        assert gate["gate_type"] == "route_direction"

    def test_no_gate_b_when_viable_branch_exists(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract(
            budget=TaskBudget(max_actions=10)
        )
        executor = RunExecutor(contract, kernel)
        executor._run_id = kernel.start_run(contract.task_id)
        executor.action_seq = 9
        # Add a succeeded node in the same stage
        from hi_agent.contracts import NodeType, TrajectoryNode, deterministic_id

        node = TrajectoryNode(
            node_id="test-node",
            node_type=NodeType.ACTION,
            stage_id="S2_gather",
            branch_id="b0",
            state=NodeState.SUCCEEDED,
        )
        executor.dag["test-node"] = node

        executor._check_human_gate_triggers(
            "S2_gather",
            {},
            failure_code=None,
        )

        # No gate should be opened because there is a viable branch
        route_gates = [
            g for g in kernel.gates.values()
            if g["gate_type"] == "route_direction"
        ]
        assert len(route_gates) == 0


class TestHumanGateQualityThreshold:
    """Gate C triggered when quality_score is below threshold."""

    def test_gate_c_on_low_quality(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(
            contract, kernel, human_gate_quality_threshold=0.5
        )
        executor._run_id = kernel.start_run(contract.task_id)

        executor._check_human_gate_triggers(
            "S3_build",
            {"quality_score": 0.3},
            failure_code=None,
        )

        assert len(kernel.gates) == 1
        gate = list(kernel.gates.values())[0]
        assert gate["gate_type"] == "artifact_review"

    def test_no_gate_c_when_quality_acceptable(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(
            contract, kernel, human_gate_quality_threshold=0.5
        )
        executor._run_id = kernel.start_run(contract.task_id)

        executor._check_human_gate_triggers(
            "S3_build",
            {"quality_score": 0.8},
            failure_code=None,
        )

        assert len(kernel.gates) == 0


class TestHumanGateIrreversibleAction:
    """Gate D triggered on irreversible_submit side effect class."""

    def test_gate_d_on_irreversible_submit(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel)
        executor._run_id = kernel.start_run(contract.task_id)

        executor._check_human_gate_triggers(
            "S5_finalize",
            {"side_effect_class": "irreversible_submit"},
            failure_code=None,
        )

        assert len(kernel.gates) == 1
        gate = list(kernel.gates.values())[0]
        assert gate["gate_type"] == "final_approval"


# ===========================================================================
# 4. Backward compatibility
# ===========================================================================


class TestBackwardCompatibility:
    """All new params default to None -- same behavior as before."""

    def test_all_new_params_none(self) -> None:
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel)

        # Should not have any of the new integrations
        assert executor.evolve_engine is None
        assert executor.harness_executor is None

        result = executor.execute()

        assert result == "completed"
        # No gates opened in normal execution (no triggers)
        # (gates may or may not be opened depending on action results,
        #  but the run should complete without errors)

    def test_existing_api_unchanged(self) -> None:
        """Verify original constructor params still work."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(
            contract,
            kernel,
            action_max_retries=2,
            runner_role="test_role",
        )

        result = executor.execute()

        assert result == "completed"

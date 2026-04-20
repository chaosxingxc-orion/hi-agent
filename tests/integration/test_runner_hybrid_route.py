"""Integration tests for RunExecutor route-engine injection behavior."""

from typing import ClassVar

from hi_agent.contracts import TaskContract
from hi_agent.route_engine.base import BranchProposal
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


class FakeHybridRouteEngine:
    """Hybrid-like route engine used to verify runner integration."""

    STAGE_ACTIONS: ClassVar[dict[str, str]] = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    def __init__(self) -> None:
        """Track calls for assertions."""
        self.calls: list[tuple[str, str, int]] = []

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        """Return deterministic proposals with one stage marked as fallback."""
        self.calls.append((stage_id, run_id, seq))
        action_kind = self.STAGE_ACTIONS[stage_id]
        if stage_id == "S3_build":
            return [
                BranchProposal(
                    branch_id=f"fallback-{stage_id}-{seq}",
                    rationale="fallback: llm route",
                    action_kind=action_kind,
                )
            ]
        return [
            BranchProposal(
                branch_id=f"rule-{stage_id}-{seq}",
                rationale="rule route",
                action_kind=action_kind,
            )
        ]


def test_runner_uses_injected_route_engine_proposals() -> None:
    """Injected route engine proposals should be used as-is by the runner."""
    contract = TaskContract(task_id="int-hybrid-001", goal="use injected route engine")
    kernel = MockKernel(strict_mode=True)
    hybrid = FakeHybridRouteEngine()
    executor = RunExecutor(contract, kernel, route_engine=hybrid)

    result = executor.execute()

    assert result == "completed"
    assert len(hybrid.calls) == 5
    action_planned = [
        event
        for event in executor.event_emitter.events
        if event.event_type == "ActionPlanned" and event.payload.get("stage_id") == "S3_build"
    ]
    assert len(action_planned) == 1
    assert str(action_planned[0].payload.get("branch_id", "")).startswith("fallback-")


def test_runner_default_route_engine_remains_backward_compatible() -> None:
    """Without injection, runner should keep using built-in RuleRouteEngine."""
    contract = TaskContract(task_id="int-hybrid-002", goal="default route remains stable")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel)

    result = executor.execute()

    assert result == "completed"
    assert len(kernel.task_views) == 5

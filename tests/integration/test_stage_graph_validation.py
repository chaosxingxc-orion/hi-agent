"""Stage graph validation integration tests.

Validates stage graph formal checks including:
- Default TRACE graph (S1->S5) passes all validations
- Custom graph with Gate D stage and gate completeness
- Dead-end detection in graphs
- Integration with runner using validated graph
"""

from __future__ import annotations

from hi_agent.contracts import StageState, TaskContract, deterministic_id
from hi_agent.contracts.cts_budget import CTSBudget
from hi_agent.route_engine.base import BranchProposal
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


class _AnalyzeGoalRouteEngine:
    """Route engine that always proposes 'analyze_goal' for any stage."""

    def propose(
        self, stage_id: str, run_id: str, seq: int,
    ) -> list[BranchProposal]:
        branch_id = deterministic_id(run_id, stage_id, str(seq))
        return [
            BranchProposal(
                branch_id=branch_id,
                rationale=f"custom: analyze_goal for {stage_id}",
                action_kind="analyze_goal",
            )
        ]
from hi_agent.trajectory.stage_graph import (
    StageGraph,
    ValidationReport,
    build_default_trace_graph,
)


class TestDefaultTraceGraphValidation:
    """The default S1->S5 graph should pass all formal checks."""

    def test_default_graph_is_valid(self) -> None:
        """validate_all on default graph should report is_valid=True."""
        graph = build_default_trace_graph()

        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
        )

        assert isinstance(report, ValidationReport)
        assert report.is_valid is True

    def test_all_stages_reachable(self) -> None:
        """Every stage should be reachable from S1_understand."""
        graph = build_default_trace_graph()

        unreachable = graph.validate_reachability_from("S1_understand")

        assert unreachable == [], f"Unreachable stages: {unreachable}"

    def test_terminal_reachable_from_all_stages(self) -> None:
        """S5_review should be reachable from every stage."""
        graph = build_default_trace_graph()

        cannot_reach = graph.validate_terminal_reachability({"S5_review"})

        assert cannot_reach == [], f"Cannot reach terminal: {cannot_reach}"

    def test_no_dead_ends(self) -> None:
        """No non-terminal stage should have zero successors."""
        graph = build_default_trace_graph()

        dead_ends = graph.validate_no_dead_ends({"S5_review"})

        assert dead_ends == [], f"Dead-end stages: {dead_ends}"

    def test_trace_order_matches_expected_sequence(self) -> None:
        """trace_order should return the canonical S1->S5 sequence."""
        graph = build_default_trace_graph()

        order = graph.trace_order()

        assert order == [
            "S1_understand",
            "S2_gather",
            "S3_build",
            "S4_synthesize",
            "S5_review",
        ]

    def test_default_graph_no_deadlock(self) -> None:
        """The legacy has_deadlock check should return False."""
        graph = build_default_trace_graph()

        assert graph.has_deadlock({"S5_review"}) is False

    def test_validate_all_with_valid_cts_budget(self) -> None:
        """Graph validation with a valid CTS budget should pass."""
        graph = build_default_trace_graph()
        budget = CTSBudget(l0_raw_tokens=4096, l1_summary_tokens=2048, l2_index_tokens=512)

        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
            budget=budget,
        )

        assert report.is_valid is True
        assert report.budget_violations == []


class TestGateDStageGraph:
    """Custom graph with a Gate D (final_approval) stage."""

    def _build_gated_graph(self) -> StageGraph:
        """Build a graph with a Gate D stage before terminal."""
        graph = StageGraph()
        graph.add_edge("S1_understand", "S2_gather")
        graph.add_edge("S2_gather", "S3_build")
        graph.add_edge("S3_build", "S4_gate_d")
        # Gate D needs two outgoing edges: approved -> S5, rejected -> S3
        graph.add_edge("S4_gate_d", "S5_review")
        graph.add_edge("S4_gate_d", "S3_build")
        return graph

    def test_gated_graph_passes_all_checks(self) -> None:
        """Graph with properly configured Gate D should pass validation."""
        graph = self._build_gated_graph()

        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
            gate_stages={"S4_gate_d": "final_approval"},
        )

        assert report.is_valid is True
        assert report.incomplete_gates == []

    def test_incomplete_gate_detected(self) -> None:
        """Gate with only one outgoing edge should be flagged as incomplete."""
        graph = StageGraph()
        graph.add_edge("S1_understand", "S2_gather")
        graph.add_edge("S2_gather", "S3_gate_d")
        # Only one outgoing edge from gate stage -- incomplete
        graph.add_edge("S3_gate_d", "S4_review")

        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S4_review"},
            gate_stages={"S3_gate_d": "final_approval"},
        )

        assert report.is_valid is False
        assert "S3_gate_d" in report.incomplete_gates

    def test_gate_completeness_with_two_paths(self) -> None:
        """Gate stage with two outgoing edges should pass completeness check."""
        graph = self._build_gated_graph()

        incomplete = graph.validate_gate_completeness(
            {"S4_gate_d": "final_approval"}
        )

        assert incomplete == []


class TestDeadEndDetectionInGraph:
    """Graphs with intentional dead-ends should be detected."""

    def test_dead_end_stage_detected(self) -> None:
        """Non-terminal stage with no successors should be flagged."""
        graph = StageGraph()
        graph.add_edge("S1_understand", "S2_gather")
        graph.add_edge("S2_gather", "S3_dead_end")
        # S3_dead_end has no outgoing edges and is not terminal
        graph.add_edge("S1_understand", "S4_review")

        dead_ends = graph.validate_no_dead_ends({"S4_review"})

        assert "S3_dead_end" in dead_ends

    def test_dead_end_makes_report_invalid(self) -> None:
        """A dead-end should cause validate_all to report is_valid=False."""
        graph = StageGraph()
        graph.add_edge("S1_understand", "S2_dead")
        graph.add_edge("S1_understand", "S3_review")
        # S2_dead has no outgoing edges

        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S3_review"},
        )

        assert report.is_valid is False
        assert "S2_dead" in report.dead_end_stages

    def test_unreachable_stage_detected(self) -> None:
        """Stage not reachable from initial should be flagged."""
        graph = StageGraph()
        graph.add_edge("S1_understand", "S2_gather")
        graph.add_edge("S2_gather", "S3_review")
        # S4_orphan is in the graph but not reachable from S1
        graph.add_edge("S4_orphan", "S3_review")

        unreachable = graph.validate_reachability_from("S1_understand")

        assert "S4_orphan" in unreachable

    def test_invalid_cts_budget_detected(self) -> None:
        """CTS budget with non-positive values should produce violations."""
        graph = build_default_trace_graph()
        bad_budget = CTSBudget(l0_raw_tokens=0, l1_summary_tokens=2048, l2_index_tokens=512)

        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
            budget=bad_budget,
        )

        assert report.is_valid is False
        assert len(report.budget_violations) > 0


class TestStageGraphWithRunner:
    """Runner should use a validated graph for execution."""

    def test_runner_uses_default_validated_graph(self) -> None:
        """Runner with default graph should complete all 5 stages."""
        contract = TaskContract(task_id="graph-run-001", goal="graph integration")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel)

        result = executor.execute()

        assert result == "completed"
        for stage_id in STAGES:
            kernel.assert_stage_state(stage_id, StageState.COMPLETED)

    def test_runner_with_custom_graph(self) -> None:
        """Runner should respect a custom stage graph's traversal order."""
        graph = StageGraph()
        graph.add_edge("A", "B")
        graph.add_edge("B", "C")

        contract = TaskContract(task_id="graph-run-002", goal="custom graph")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(
            contract, kernel,
            stage_graph=graph,
            route_engine=_AnalyzeGoalRouteEngine(),
        )

        result = executor.execute()

        assert result == "completed"
        kernel.assert_stage_state("A", StageState.COMPLETED)
        kernel.assert_stage_state("B", StageState.COMPLETED)
        kernel.assert_stage_state("C", StageState.COMPLETED)

    def test_runner_graph_trace_order(self) -> None:
        """Runner should iterate stages in the graph's trace_order."""
        graph = StageGraph()
        graph.add_edge("X1", "X2")
        graph.add_edge("X2", "X3")

        contract = TaskContract(task_id="graph-run-003", goal="order check")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(
            contract, kernel,
            stage_graph=graph,
            route_engine=_AnalyzeGoalRouteEngine(),
        )

        executor.execute()

        # Verify stages were opened in order via kernel events
        opened = [
            e["stage_id"] for e in kernel.events
            if e["event_type"] == "StageOpened"
        ]
        assert opened == ["X1", "X2", "X3"]

    def test_validated_graph_before_runner_execution(self) -> None:
        """A pre-validated graph should work seamlessly with runner."""
        graph = build_default_trace_graph()
        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
        )
        assert report.is_valid is True

        contract = TaskContract(task_id="graph-run-004", goal="validated graph")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, stage_graph=graph)

        result = executor.execute()

        assert result == "completed"

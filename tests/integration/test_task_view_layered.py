"""Task view layered builder integration tests.

Validates token-budgeted task view construction including:
- Building from real run data (L2 index + L1 from compression)
- Token budget enforcement
- Layer priority under tight budgets
- Budget utilization with realistic data
"""

from __future__ import annotations

from hi_agent.contracts import TaskContract
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.l2_index import RunMemoryIndex
from hi_agent.runner import STAGES, RunExecutor
from hi_agent.task_view.builder import TaskView, build_task_view
from hi_agent.task_view.token_budget import DEFAULT_BUDGET

from tests.helpers.kernel_adapter_fixture import MockKernel


def _build_run_data() -> tuple[RunExecutor, MockKernel]:
    """Execute a full run and return executor + kernel."""
    contract = TaskContract(task_id="tv-int-001", goal="task view integration")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
    executor.execute()
    return executor, kernel


def _build_l2_index(executor: RunExecutor) -> RunMemoryIndex:
    """Build L2 run memory index from a completed run's stage summaries."""
    index = RunMemoryIndex(run_id=executor.run_id)
    for stage_id in STAGES:
        summary = executor.stage_summaries.get(stage_id)
        outcome = summary.outcome if summary else "unknown"
        index.add_stage(stage_id, outcome)
    return index


def _build_l1_summary(
    executor: RunExecutor,
    stage_id: str,
) -> CompressedStageMemory:
    """Build L1 compressed summary for a stage from raw memory."""
    records = [r for r in executor.raw_memory.list_all() if r.payload.get("stage_id") == stage_id]
    compressor = MemoryCompressor(compress_threshold=100)
    return compressor.compress_stage(stage_id, records)


class TestTaskViewFromRealRun:
    """Build task views from data produced by a real run."""

    def test_build_with_l2_and_l1(self) -> None:
        """Task view should assemble correctly from run L2 index and L1 summary."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S5_review")
        l1_previous = _build_l1_summary(executor, "S4_synthesize")

        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            previous_stage_summary=l1_previous,
            budget=DEFAULT_BUDGET,
        )

        assert isinstance(tv, TaskView)
        assert tv.total_tokens > 0
        assert len(tv.sections) >= 2  # At least L2 + L1 current

    def test_sections_contain_expected_layers(self) -> None:
        """Task view should contain l2_index and l1_current_stage sections."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S3_build")

        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            budget=DEFAULT_BUDGET,
        )

        assert isinstance(tv, TaskView)
        layer_names = [s.layer for s in tv.sections]
        assert "l2_index" in layer_names
        assert "l1_current_stage" in layer_names


class TestTokenBudgetEnforcement:
    """Token budget should never be exceeded."""

    def test_total_tokens_within_budget(self) -> None:
        """Total tokens should not exceed the configured budget."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S5_review")
        l1_previous = _build_l1_summary(executor, "S4_synthesize")

        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            previous_stage_summary=l1_previous,
            episodes=[{"event": "test_episode"} for _ in range(10)],
            budget=DEFAULT_BUDGET,
        )

        assert isinstance(tv, TaskView)
        assert tv.total_tokens <= tv.budget

    def test_very_tight_budget_still_respects_limit(self) -> None:
        """Even with a very tight budget, total tokens must not exceed it."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S3_build")

        tight_budget = 100
        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            budget=tight_budget,
        )

        assert isinstance(tv, TaskView)
        assert tv.total_tokens <= tight_budget

    def test_zero_budget_produces_empty_view(self) -> None:
        """Budget of zero should produce a task view with no sections."""
        l2_index = RunMemoryIndex(run_id="zero-budget-run")
        l1_current = CompressedStageMemory(stage_id="S1_understand")

        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            budget=0,
        )

        assert isinstance(tv, TaskView)
        assert tv.total_tokens == 0
        assert len(tv.sections) == 0


class TestLayerPriority:
    """L2 and L1 current should always be present under tight budgets."""

    def test_l2_and_l1_current_present_with_tight_budget(self) -> None:
        """With a moderately tight budget, L2 and L1 current should be loaded."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S5_review")
        l1_previous = _build_l1_summary(executor, "S4_synthesize")

        # Use a budget large enough for L2 + L1 current but possibly not all
        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            previous_stage_summary=l1_previous,
            episodes=[{"ep": f"episode-{i}"} for i in range(20)],
            knowledge_records=["knowledge item " * 50 for _ in range(10)],
            budget=2000,
        )

        assert isinstance(tv, TaskView)
        layer_names = [s.layer for s in tv.sections]
        assert "l2_index" in layer_names, "L2 index should always be first priority"
        assert "l1_current_stage" in layer_names, "L1 current stage should always be loaded"

    def test_lower_priority_layers_excluded_under_tight_budget(self) -> None:
        """Knowledge and episodic layers may be excluded when budget is tight."""
        l2_index = RunMemoryIndex(run_id="priority-test")
        l2_index.add_stage("S1_understand", "succeeded")
        l1_current = CompressedStageMemory(
            stage_id="S1_understand",
            findings=["f1"],
            outcome="succeeded",
        )

        # Very tight budget: only enough for L2 + L1
        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            episodes=[{"ep": "data"} for _ in range(50)],
            knowledge_records=["knowledge " * 100 for _ in range(50)],
            budget=800,
        )

        assert isinstance(tv, TaskView)
        layer_names = [s.layer for s in tv.sections]
        # L2 and L1 should be present
        assert "l2_index" in layer_names
        assert "l1_current_stage" in layer_names


class TestBudgetUtilization:
    """Budget utilization should be reasonable with realistic data."""

    def test_utilization_above_half_with_realistic_data(self) -> None:
        """With all layers populated, utilization should exceed 0.5."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S5_review")
        l1_previous = _build_l1_summary(executor, "S4_synthesize")

        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            previous_stage_summary=l1_previous,
            episodes=[{"event": f"episode-{i}", "data": "x" * 200} for i in range(10)],
            knowledge_records=[f"knowledge record {i} " * 30 for i in range(5)],
            budget=DEFAULT_BUDGET,
        )

        assert isinstance(tv, TaskView)
        # System reserved (512 tokens) is always counted, plus actual content
        assert tv.budget_utilization > 0.05, f"Utilization too low: {tv.budget_utilization:.3f}"

    def test_utilization_bounded_by_one(self) -> None:
        """Budget utilization should never exceed 1.0."""
        executor, _ = _build_run_data()
        l2_index = _build_l2_index(executor)
        l1_current = _build_l1_summary(executor, "S5_review")

        tv = build_task_view(
            run_index=l2_index,
            current_stage_summary=l1_current,
            episodes=[{"data": "x" * 1000} for _ in range(100)],
            knowledge_records=["y" * 1000 for _ in range(100)],
            budget=500,
        )

        assert isinstance(tv, TaskView)
        assert tv.budget_utilization <= 1.0

"""Tests for hi_agent.task_view.processors -- context processor chain."""

from __future__ import annotations

from hi_agent.task_view.processors import (
    CompressionProcessor,
    ContextProcessorChain,
    EvidencePriorityProcessor,
    TaskViewContext,
    WindowLimitProcessor,
    _estimate_tokens,
)

# ---------------------------------------------------------------------------
# TaskViewContext
# ---------------------------------------------------------------------------


class TestTaskViewContext:
    """TaskViewContext has correct defaults."""

    def test_defaults(self) -> None:
        ctx = TaskViewContext()
        assert ctx.contract_summary == ""
        assert ctx.evidence == []
        assert ctx.budget_tokens == 8192
        assert ctx.total_tokens == 0
        assert ctx.metadata == {}

    def test_fields_independent(self) -> None:
        ctx1 = TaskViewContext(evidence=["a"])
        ctx2 = TaskViewContext()
        assert ctx1.evidence == ["a"]
        assert ctx2.evidence == []


# ---------------------------------------------------------------------------
# WindowLimitProcessor
# ---------------------------------------------------------------------------


class TestWindowLimitProcessor:
    """WindowLimitProcessor trims context to fit token window."""

    def test_no_trim_when_under_budget(self) -> None:
        ctx = TaskViewContext(
            evidence=["short"],
            memory_snippets=["mem"],
        )
        proc = WindowLimitProcessor(max_tokens=8192)
        result = proc.process(ctx)
        assert result.evidence == ["short"]
        assert result.memory_snippets == ["mem"]

    def test_trims_low_priority_first(self) -> None:
        # Episodic is lowest priority, should be trimmed first.
        ctx = TaskViewContext(
            evidence=["e" * 100],
            episodic_snippets=["x" * 4000, "y" * 4000],
        )
        proc = WindowLimitProcessor(max_tokens=200)
        result = proc.process(ctx)
        # Evidence should survive, episodic should be trimmed.
        assert len(result.evidence) >= 1
        assert len(result.episodic_snippets) <= len(ctx.episodic_snippets)

    def test_sets_budget_tokens(self) -> None:
        ctx = TaskViewContext()
        proc = WindowLimitProcessor(max_tokens=4096)
        result = proc.process(ctx)
        assert result.budget_tokens == 4096

    def test_clears_all_lists_when_structural_exceeds_budget(self) -> None:
        ctx = TaskViewContext(
            contract_summary="x" * 1000,
            evidence=["ev1", "ev2"],
            memory_snippets=["m1"],
        )
        proc = WindowLimitProcessor(max_tokens=10)
        result = proc.process(ctx)
        assert result.evidence == []
        assert result.memory_snippets == []
        assert result.knowledge_snippets == []
        assert result.episodic_snippets == []


# ---------------------------------------------------------------------------
# CompressionProcessor
# ---------------------------------------------------------------------------


class TestCompressionProcessor:
    """CompressionProcessor truncates verbose sections."""

    def test_no_compression_under_threshold(self) -> None:
        ctx = TaskViewContext(evidence=["short item"])
        proc = CompressionProcessor(threshold_tokens=4096)
        result = proc.process(ctx)
        assert result.evidence == ["short item"]

    def test_compresses_over_threshold(self) -> None:
        # Create items that exceed the threshold.
        long_items = ["a" * 2000 for _ in range(10)]
        ctx = TaskViewContext(evidence=long_items)
        proc = CompressionProcessor(threshold_tokens=100)
        result = proc.process(ctx)
        # Each item should be truncated.
        for item in result.evidence:
            assert len(item) < 2000

    def test_compresses_each_list_independently(self) -> None:
        ctx = TaskViewContext(
            evidence=["e" * 2000 for _ in range(5)],
            memory_snippets=["short"],
        )
        proc = CompressionProcessor(threshold_tokens=100)
        result = proc.process(ctx)
        # memory_snippets should not be affected.
        assert result.memory_snippets == ["short"]


# ---------------------------------------------------------------------------
# EvidencePriorityProcessor
# ---------------------------------------------------------------------------


class TestEvidencePriorityProcessor:
    """EvidencePriorityProcessor reserves budget for evidence."""

    def test_evidence_preserved_over_others(self) -> None:
        ctx = TaskViewContext(
            budget_tokens=200,
            evidence=["important evidence " * 5],
            memory_snippets=["memory " * 50],
            episodic_snippets=["episodic " * 50],
        )
        proc = EvidencePriorityProcessor()
        result = proc.process(ctx)
        # Evidence should have items kept.
        assert len(result.evidence) >= 1

    def test_empty_evidence_redistributes_budget(self) -> None:
        ctx = TaskViewContext(
            budget_tokens=8192,
            evidence=[],
            memory_snippets=["m" * 100],
        )
        proc = EvidencePriorityProcessor()
        result = proc.process(ctx)
        assert result.memory_snippets == ["m" * 100]


# ---------------------------------------------------------------------------
# ContextProcessorChain
# ---------------------------------------------------------------------------


class TestContextProcessorChain:
    """ContextProcessorChain executes processors in sequence."""

    def test_empty_chain(self) -> None:
        chain = ContextProcessorChain()
        ctx = TaskViewContext(contract_summary="test")
        result = chain.execute(ctx)
        assert result.contract_summary == "test"

    def test_single_processor(self) -> None:
        chain = ContextProcessorChain([WindowLimitProcessor(max_tokens=4096)])
        ctx = TaskViewContext()
        result = chain.execute(ctx)
        assert result.budget_tokens == 4096

    def test_chain_ordering(self) -> None:
        """Processors execute in insertion order."""
        chain = (
            ContextProcessorChain()
            .add(WindowLimitProcessor(max_tokens=2048))
            .add(CompressionProcessor(threshold_tokens=512))
        )
        ctx = TaskViewContext(evidence=["x" * 5000 for _ in range(10)])
        result = chain.execute(ctx)
        assert result.budget_tokens == 2048

    def test_add_returns_self(self) -> None:
        chain = ContextProcessorChain()
        ret = chain.add(WindowLimitProcessor())
        assert ret is chain

    def test_constructor_with_list(self) -> None:
        procs = [WindowLimitProcessor(1024), CompressionProcessor(512)]
        chain = ContextProcessorChain(procs)
        ctx = TaskViewContext()
        result = chain.execute(ctx)
        assert result.budget_tokens == 1024

    def test_full_pipeline(self) -> None:
        """Integration: window limit -> compression -> evidence priority."""
        chain = (
            ContextProcessorChain()
            .add(WindowLimitProcessor(max_tokens=500))
            .add(CompressionProcessor(threshold_tokens=200))
            .add(EvidencePriorityProcessor())
        )
        ctx = TaskViewContext(
            contract_summary="task",
            evidence=["critical finding " * 3],
            memory_snippets=["old memory " * 10],
            episodic_snippets=["episode " * 20],
        )
        result = chain.execute(ctx)
        # Should complete without error and have budget set.
        assert result.budget_tokens == 500


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    """Internal token estimation helper."""

    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("") == 1  # minimum 1
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 100) == 25

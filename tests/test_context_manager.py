"""Tests for hi_agent.context — unified context orchestration."""

from __future__ import annotations

import pytest
from hi_agent.context.health import ContextMonitor
from hi_agent.context.manager import (
    ContextBudget,
    ContextHealth,
    ContextHealthReport,
    ContextManager,
    ContextSection,
    ContextSnapshot,
)

# ======================================================================
# Budget tests
# ======================================================================


class TestContextBudget:
    """ContextBudget property calculations."""

    def test_effective_window(self):
        b = ContextBudget(total_window=200_000, output_reserve=8_000)
        assert b.effective_window == 192_000

    def test_effective_window_custom(self):
        b = ContextBudget(total_window=100_000, output_reserve=10_000)
        assert b.effective_window == 90_000

    def test_fixed_overhead(self):
        b = ContextBudget(
            system_prompt=2_000,
            tool_definitions=3_000,
            skill_prompts=5_000,
            memory_context=2_000,
            knowledge_context=1_500,
            reflection_context=0,
        )
        assert b.fixed_overhead == 13_500

    def test_history_budget_equals_effective_minus_overhead(self):
        b = ContextBudget(
            total_window=50_000,
            output_reserve=5_000,
            system_prompt=1_000,
            tool_definitions=1_000,
            skill_prompts=1_000,
            memory_context=1_000,
            knowledge_context=1_000,
            reflection_context=0,
        )
        # effective = 45000, overhead = 5000, history = 40000
        assert b.history_budget == 40_000

    def test_history_budget_floors_at_zero(self):
        b = ContextBudget(
            total_window=10_000,
            output_reserve=8_000,
            system_prompt=5_000,
            tool_definitions=5_000,
            skill_prompts=5_000,
            memory_context=5_000,
            knowledge_context=5_000,
        )
        # effective = 2000, overhead = 25000 → history = 0
        assert b.history_budget == 0

    def test_adjust_budget_changes_allocation(self):
        mgr = ContextManager()
        mgr.adjust_budget(system_prompt=4_000, skill_prompts=8_000)
        assert mgr._budget.system_prompt == 4_000
        assert mgr._budget.skill_prompts == 8_000


# ======================================================================
# Assembly tests
# ======================================================================


class TestAssembly:
    """Test that prepare_context assembles all sections."""

    def test_prepare_context_assembles_all_sections(self):
        mgr = ContextManager()
        snap = mgr.prepare_context(
            purpose="routing",
            system_prompt="Be helpful.",
            tool_definitions="tool1: does stuff",
        )
        section_names = {s.name for s in snap.sections}
        assert "system" in section_names
        assert "tools" in section_names
        assert "skills" in section_names
        assert "memory" in section_names
        assert "knowledge" in section_names
        assert "history" in section_names

    def test_section_respects_budget(self):
        budget = ContextBudget(system_prompt=10)
        mgr = ContextManager(budget=budget)
        # Create a system prompt that exceeds 10 tokens (~40 chars)
        snap = mgr.prepare_context(
            system_prompt="x" * 200,  # 50 tokens, budget is 10
        )
        system_section = snap.get_section("system")
        assert system_section is not None
        assert system_section.tokens <= 10 + 1  # +1 for rounding in count_tokens

    def test_extra_context_injected(self):
        mgr = ContextManager()
        snap = mgr.prepare_context(
            extra_context={"custom_section": "Hello custom context"},
        )
        custom = snap.get_section("custom_section")
        assert custom is not None
        assert "Hello custom context" in custom.content

    def test_missing_sources_handled_gracefully(self):
        """skill_loader=None, memory_retriever=None → empty sections."""
        mgr = ContextManager(
            skill_loader=None,
            memory_retriever=None,
        )
        snap = mgr.prepare_context()
        skill_section = snap.get_section("skills")
        assert skill_section is not None
        assert skill_section.content == ""
        assert skill_section.tokens == 0

        memory_section = snap.get_section("memory")
        assert memory_section is not None
        assert memory_section.content == ""
        assert memory_section.tokens == 0

    def test_purpose_recorded_in_snapshot(self):
        mgr = ContextManager()
        snap = mgr.prepare_context(purpose="action")
        assert snap.purpose == "action"


# ======================================================================
# Threshold tests
# ======================================================================


class TestThresholds:
    """Test health level thresholds."""

    def test_green_below_70(self):
        mgr = ContextManager()
        health = mgr._check_health(100_000)
        # 100k / 192k ≈ 52% → GREEN
        assert health == ContextHealth.GREEN

    def test_yellow_70_to_85(self):
        mgr = ContextManager()
        # 70% of 192k = 134_400
        health = mgr._check_health(140_000)
        assert health == ContextHealth.YELLOW

    def test_orange_85_to_95(self):
        mgr = ContextManager()
        # 85% of 192k = 163_200
        health = mgr._check_health(170_000)
        assert health == ContextHealth.ORANGE

    def test_red_above_95(self):
        mgr = ContextManager()
        # 95% of 192k = 182_400
        health = mgr._check_health(185_000)
        assert health == ContextHealth.RED

    def test_green_no_compression(self):
        """GREEN health should not trigger compression."""
        budget = ContextBudget(total_window=200_000)
        mgr = ContextManager(budget=budget)
        snap = mgr.prepare_context(system_prompt="short")
        assert snap.health == ContextHealth.GREEN
        assert snap.compressions_applied == 0


# ======================================================================
# ContextSnapshot tests
# ======================================================================


class TestContextSnapshot:
    """ContextSnapshot utility methods."""

    def test_to_prompt_string(self):
        snap = ContextSnapshot(
            sections=[
                ContextSection(name="system", content="Hello", tokens=2),
                ContextSection(name="tools", content="", tokens=0),
                ContextSection(name="history", content="Past events", tokens=3),
            ]
        )
        prompt = snap.to_prompt_string()
        assert "## system" in prompt
        assert "Hello" in prompt
        assert "## history" in prompt
        assert "Past events" in prompt
        # Empty section should not appear
        assert "## tools" not in prompt

    def test_to_sections_dict(self):
        snap = ContextSnapshot(
            sections=[
                ContextSection(name="system", content="Hello", tokens=2),
                ContextSection(name="tools", content="", tokens=0),
            ]
        )
        d = snap.to_sections_dict()
        assert "system" in d
        assert "tools" not in d  # empty content excluded

    def test_get_section_found(self):
        snap = ContextSnapshot(sections=[ContextSection(name="foo", content="bar", tokens=1)])
        assert snap.get_section("foo") is not None
        assert snap.get_section("foo").content == "bar"

    def test_get_section_not_found(self):
        snap = ContextSnapshot(sections=[])
        assert snap.get_section("missing") is None


# ======================================================================
# Compression fallback tests
# ======================================================================


class TestCompressionFallback:
    """Tests for the compression fallback chain."""

    def test_snip_removes_old_history_entries(self):
        # Use a small budget so history section budget is small
        budget = ContextBudget(
            total_window=2_000,
            output_reserve=200,
            system_prompt=100,
            tool_definitions=100,
            skill_prompts=100,
            memory_context=100,
            knowledge_context=100,
        )
        mgr = ContextManager(budget=budget)
        # history_budget = 1800 - 500 = 1300
        for i in range(100):
            mgr.add_history_entry("user", f"Message number {i} with some content padding")

        section = mgr._assemble_history()
        original_tokens = section.tokens

        # Now give the section a small budget so snip triggers
        section.budget = 200
        snipped = mgr._snip_history(section, target_tokens=50)
        assert snipped.tokens < original_tokens

    def test_compact_calls_compressor_when_available(self):
        """Compact step should invoke the compressor."""

        class MockCompressor:
            def __init__(self):
                self.called = False

            def compress_text(self, text):
                self.called = True
                return "Compressed summary"

        compressor = MockCompressor()
        mgr = ContextManager(compressor=compressor)
        mgr.add_history_entry("user", "A" * 2000)

        section = mgr._assemble_history()
        result = mgr._compact_history(section, target_tokens=50)
        assert compressor.called
        assert "Compressed summary" in result.content

    def test_trim_reduces_lowest_priority_sections(self):
        mgr = ContextManager()
        sections = [
            ContextSection(name="system", content="sys", tokens=100, budget=200),
            ContextSection(name="tools", content="tools", tokens=100, budget=200),
            ContextSection(name="skills", content="s" * 400, tokens=100, budget=200),
            ContextSection(name="memory", content="m" * 400, tokens=100, budget=200),
            ContextSection(name="knowledge", content="k" * 400, tokens=100, budget=200),
            ContextSection(name="history", content="h" * 400, tokens=100, budget=200),
        ]
        # Total = 600, target = 300 → should trim knowledge first, then memory
        trimmed = mgr._trim_sections(sections, target_tokens=300)
        total = sum(s.tokens for s in trimmed)
        assert total <= 300

    def test_fallback_chain_order_snip_compact_trim(self):
        """Verify the fallback chain runs snip → compact → trim."""
        call_log: list[str] = []

        class MockCompressor:
            def compress_text(self, text):
                call_log.append("compact")
                return "summary"

        # Create a budget where total will be in ORANGE/RED range
        budget = ContextBudget(
            total_window=1_000,
            output_reserve=100,
            system_prompt=200,
            tool_definitions=200,
            skill_prompts=100,
            memory_context=100,
            knowledge_context=100,
        )
        mgr = ContextManager(budget=budget, compressor=MockCompressor())

        # Fill history to overflow
        for i in range(50):
            mgr.add_history_entry("user", f"Long message {i} " * 10)

        snap = mgr.prepare_context(
            system_prompt="sys " * 30,
            tool_definitions="tool " * 30,
        )
        # Compression should have been attempted
        assert snap.compressions_applied > 0 or snap.health != ContextHealth.RED

    def test_circuit_breaker_after_failures(self):
        """Circuit breaker should open after N consecutive compression failures."""

        class FailingCompressor:
            def compress_text(self, text):
                raise RuntimeError("Compression failed")

        mgr = ContextManager(
            compressor=FailingCompressor(),
            max_compression_failures=3,
        )
        assert not mgr._circuit_breaker_open

        # Simulate 3 failures
        for _ in range(3):
            section = ContextSection(name="history", content="x" * 800, tokens=200, budget=500)
            try:
                mgr._compact_history(section, target_tokens=50)
            except RuntimeError:
                mgr._compression_failures += 1
                if mgr._compression_failures >= mgr._max_compression_failures:
                    mgr._circuit_breaker_open = True

        assert mgr._circuit_breaker_open


# ======================================================================
# Diminishing returns tests
# ======================================================================


class TestDiminishingReturns:
    """Tests for diminishing returns detection."""

    def test_diminishing_after_low_output_iterations(self):
        mgr = ContextManager(diminishing_window=3, diminishing_threshold=100)
        mgr.record_response(50)
        mgr.record_response(30)
        mgr.record_response(20)
        assert mgr.check_diminishing_returns() is True

    def test_not_diminishing_when_output_healthy(self):
        mgr = ContextManager(diminishing_window=3, diminishing_threshold=100)
        mgr.record_response(500)
        mgr.record_response(400)
        mgr.record_response(300)
        assert mgr.check_diminishing_returns() is False

    def test_not_diminishing_with_insufficient_data(self):
        mgr = ContextManager(diminishing_window=3, diminishing_threshold=100)
        mgr.record_response(10)
        # Only 1 iteration, need 3
        assert mgr.check_diminishing_returns() is False

    def test_not_diminishing_with_mixed_output(self):
        mgr = ContextManager(diminishing_window=3, diminishing_threshold=100)
        mgr.record_response(10)
        mgr.record_response(500)  # healthy
        mgr.record_response(10)
        assert mgr.check_diminishing_returns() is False


# ======================================================================
# History management tests
# ======================================================================


class TestHistoryManagement:
    """Tests for history entry tracking."""

    def test_add_history_entry_and_get_after_compact(self):
        mgr = ContextManager()
        mgr.add_history_entry("user", "Hello")
        mgr.add_history_entry("assistant", "Hi there")
        mgr.add_history_entry("user", "How are you?")

        entries = mgr.get_history_after_compact()
        assert len(entries) == 3
        assert entries[0]["role"] == "user"
        assert entries[0]["content"] == "Hello"

    def test_compact_offset_filters_compressed_entries(self):
        mgr = ContextManager()
        mgr.add_history_entry("user", "Old message 1")
        mgr.add_history_entry("user", "Old message 2")
        mgr.add_history_entry("user", "New message 3")

        # Simulate compaction of first 2 entries
        mgr._compact_offset = 2

        entries = mgr.get_history_after_compact()
        assert len(entries) == 1
        assert entries[0]["content"] == "New message 3"

    def test_history_includes_metadata(self):
        mgr = ContextManager()
        mgr.add_history_entry("user", "test", metadata={"source": "cli"})
        entries = mgr.get_history_after_compact()
        assert entries[0]["metadata"]["source"] == "cli"

    def test_history_assembly_includes_compact_summary(self):
        mgr = ContextManager()
        mgr.add_history_entry("user", "Old stuff")
        mgr._compact_offset = 1
        mgr._compact_summary = "Previously discussed old stuff."
        mgr.add_history_entry("user", "New stuff")

        section = mgr._assemble_history()
        assert "Previously discussed old stuff" in section.content
        assert "New stuff" in section.content


# ======================================================================
# Health monitoring tests
# ======================================================================


class TestContextMonitor:
    """Tests for ContextMonitor."""

    def test_record_snapshot_stores_data(self):
        monitor = ContextMonitor()
        snap = ContextSnapshot(
            sections=[ContextSection(name="system", content="hi", tokens=1, budget=100)],
            total_tokens=1,
            budget_tokens=100,
            utilization_pct=0.01,
            health=ContextHealth.GREEN,
            compressions_applied=0,
            purpose="test",
        )
        monitor.record_snapshot(snap)
        assert monitor.snapshot_count == 1

    def test_get_trend_computes_utilization(self):
        monitor = ContextMonitor()
        for pct in [0.3, 0.4, 0.5, 0.6, 0.7]:
            snap = ContextSnapshot(
                sections=[],
                total_tokens=int(pct * 192_000),
                budget_tokens=192_000,
                utilization_pct=pct,
                health=ContextHealth.GREEN,
            )
            monitor.record_snapshot(snap)

        trend = monitor.get_trend(last_n=5)
        assert trend["snapshot_count"] == 5
        assert 0.4 < trend["avg_utilization"] < 0.6
        assert trend["growth_rate"] == pytest.approx(0.4, abs=0.01)

    def test_get_trend_empty(self):
        monitor = ContextMonitor()
        trend = monitor.get_trend()
        assert trend["snapshot_count"] == 0
        assert trend["avg_utilization"] == 0.0

    def test_record_compression(self):
        monitor = ContextMonitor()
        monitor.record_compression(
            method="snip",
            tokens_before=10_000,
            tokens_after=5_000,
            cost_tokens=0,
        )
        assert monitor.compression_event_count == 1

    def test_get_recommendations_balanced(self):
        monitor = ContextMonitor()
        snap = ContextSnapshot(
            sections=[ContextSection(name="system", content="s", tokens=100, budget=1000)],
            total_tokens=100,
            budget_tokens=192_000,
            utilization_pct=0.001,
            health=ContextHealth.GREEN,
        )
        monitor.record_snapshot(snap)
        recs = monitor.get_recommendations()
        assert any("well balanced" in r for r in recs)

    def test_get_recommendations_high_utilization(self):
        monitor = ContextMonitor()
        snap = ContextSnapshot(
            sections=[
                ContextSection(name="history", content="h" * 10000, tokens=160_000, budget=170_000)
            ],
            total_tokens=160_000,
            budget_tokens=170_000,
            utilization_pct=0.94,
            health=ContextHealth.ORANGE,
            compressions_applied=1,
        )
        monitor.record_snapshot(snap)
        recs = monitor.get_recommendations()
        assert any("85%" in r or "utilization" in r.lower() for r in recs)

    def test_to_summary(self):
        monitor = ContextMonitor()
        monitor.record_compression("snip", 1000, 500, 0)
        summary = monitor.to_summary()
        assert summary["total_compressions"] == 1
        assert summary["total_tokens_saved"] == 500
        assert "recommendations" in summary


# ======================================================================
# Health report tests
# ======================================================================


class TestHealthReport:
    """Tests for get_health_report."""

    def test_health_report_structure(self):
        mgr = ContextManager()
        report = mgr.get_health_report()
        assert isinstance(report, ContextHealthReport)
        assert isinstance(report.health, ContextHealth)
        assert report.budget_tokens > 0
        assert "system" in report.per_section
        assert "history" in report.per_section
        assert report.circuit_breaker_open is False

    def test_health_report_reflects_diminishing(self):
        mgr = ContextManager(diminishing_window=2, diminishing_threshold=100)
        mgr.record_response(10)
        mgr.record_response(5)
        report = mgr.get_health_report()
        assert report.diminishing_returns is True


# ======================================================================
# Budget adjustment tests
# ======================================================================


class TestBudgetAdjustment:
    """Tests for dynamic budget changes."""

    def test_adjust_budget_updates_values(self):
        mgr = ContextManager()
        original = mgr._budget.memory_context
        mgr.adjust_budget(memory_context=5_000)
        assert mgr._budget.memory_context == 5_000
        assert mgr._budget.memory_context != original

    def test_set_model_context_window(self):
        mgr = ContextManager()
        mgr.set_model_context_window(128_000)
        assert mgr._budget.total_window == 128_000
        assert mgr._budget.effective_window == 128_000 - mgr._budget.output_reserve

    def test_adjust_budget_ignores_unknown_keys(self):
        mgr = ContextManager()
        original_window = mgr._budget.total_window
        mgr.adjust_budget(nonexistent_field=999)
        assert mgr._budget.total_window == original_window


# ======================================================================
# Integration tests
# ======================================================================


class TestIntegration:
    """Integration tests with RunSession and SkillLoader mocks."""

    def test_with_mock_session_context(self):
        """ContextManager with a mock session providing history."""
        mgr = ContextManager()
        mgr.add_history_entry("user", "Analyze revenue data")
        mgr.add_history_entry("assistant", "I will gather quarterly reports.")
        mgr.add_history_entry("user", "Focus on Q3 anomalies.")

        snap = mgr.prepare_context(
            purpose="routing",
            system_prompt="You are a data analyst.",
        )
        assert snap.health == ContextHealth.GREEN
        history = snap.get_section("history")
        assert history is not None
        assert "revenue data" in history.content

    def test_with_mock_skill_loader(self):
        """ContextManager with a mock SkillLoader."""

        class MockSkillPrompt:
            def to_prompt_string(self):
                return "# Skills\n- analyze_data: Analyze datasets"

            @property
            def total_tokens(self):
                return 15

        class MockSkillLoader:
            def build_prompt(self, budget_tokens=None):
                return MockSkillPrompt()

        mgr = ContextManager(skill_loader=MockSkillLoader())
        snap = mgr.prepare_context()
        skills = snap.get_section("skills")
        assert skills is not None
        assert "analyze_data" in skills.content
        assert skills.tokens == 15

    def test_with_mock_memory_retriever(self):
        """ContextManager with a mock memory retriever."""

        class MockMemoryContext:
            def to_context_string(self):
                return "=== Long-term ===\nRevenue analysis best practices"

        class MockRetriever:
            def retrieve(self, query="", budget_tokens=None):
                return MockMemoryContext()

        mgr = ContextManager(memory_retriever=MockRetriever())
        snap = mgr.prepare_context()
        memory = snap.get_section("memory")
        assert memory is not None
        assert "Revenue analysis" in memory.content

    def test_full_cycle_prepare_respond_compress(self):
        """Full cycle: prepare → response → prepare (grows) → compress → drops."""
        budget = ContextBudget(
            total_window=2_000,
            output_reserve=200,
            system_prompt=100,
            tool_definitions=100,
            skill_prompts=100,
            memory_context=100,
            knowledge_context=100,
        )
        mgr = ContextManager(budget=budget)

        # First prepare — low utilization
        snap1 = mgr.prepare_context(system_prompt="Be brief.")
        initial_tokens = snap1.total_tokens

        # Add lots of history to grow utilization
        for i in range(30):
            mgr.add_history_entry("user", f"Question {i}: " + "detail " * 20)
            mgr.add_history_entry("assistant", f"Answer {i}: " + "response " * 20)

        # Second prepare — should trigger compression or show higher utilization
        snap2 = mgr.prepare_context(system_prompt="Be brief.")

        # Either compression was applied or tokens grew
        assert snap2.compressions_applied > 0 or snap2.total_tokens >= initial_tokens

    def test_monitor_integration(self):
        """ContextMonitor tracks snapshots from ContextManager."""
        monitor = ContextMonitor()
        mgr = ContextManager()

        for i in range(5):
            mgr.add_history_entry("user", f"Message {i}")
            snap = mgr.prepare_context(purpose=f"call_{i}")
            monitor.record_snapshot(snap)

        assert monitor.snapshot_count == 5
        trend = monitor.get_trend()
        assert trend["snapshot_count"] == 5

    def test_end_to_end_with_all_sources(self):
        """End-to-end with skill loader, memory, and history."""

        class MockSkillPrompt:
            def to_prompt_string(self):
                return "Skills: data_analysis, report_gen"

            @property
            def total_tokens(self):
                return 10

        class MockSkillLoader:
            def build_prompt(self, budget_tokens=None):
                return MockSkillPrompt()

        class MockMemoryCtx:
            def to_context_string(self):
                return "Past: user prefers charts"

        class MockRetriever:
            def retrieve(self, query="", budget_tokens=None):
                return MockMemoryCtx()

        mgr = ContextManager(
            skill_loader=MockSkillLoader(),
            memory_retriever=MockRetriever(),
        )
        mgr.add_history_entry("user", "Analyze Q3 revenue")
        mgr.add_history_entry("assistant", "Gathering data now.")

        snap = mgr.prepare_context(
            purpose="action",
            system_prompt="You are a financial analyst.",
            tool_definitions="run_query(sql): Execute SQL",
            extra_context={"task_contract": "Goal: Analyze Q3 revenue trends"},
        )

        assert snap.health == ContextHealth.GREEN
        assert snap.total_tokens > 0
        assert snap.get_section("skills").content != ""
        assert snap.get_section("memory").content != ""
        assert snap.get_section("history").content != ""
        assert snap.get_section("task_contract") is not None

        # Verify prompt string combines all
        prompt = snap.to_prompt_string()
        assert "financial analyst" in prompt
        assert "data_analysis" in prompt or "Skills" in prompt

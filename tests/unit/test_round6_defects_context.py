"""Unit tests for H-8: dedicated reflection_context partition in ContextManager."""


from hi_agent.context.manager import ContextBudget, ContextManager


class TestReflectionContextPartition:
    """Tests for the reflection_context budget field and set_reflection_context()."""

    def _make_manager(self) -> ContextManager:
        """Return a ContextManager with no external dependencies."""
        budget = ContextBudget(
            total_window=200_000,
            output_reserve=8_000,
            system_prompt=2_000,
            tool_definitions=3_000,
            skill_prompts=5_000,
            memory_context=1_500,
            knowledge_context=1_500,
            reflection_context=500,
        )
        return ContextManager(budget=budget)

    def test_both_partitions_untruncated_when_within_budget(self):
        """Inject 1,800 chars into knowledge and 300 chars into reflection;
        assert both appear untruncated in the assembled context snapshot.

        memory_context budget = 1_500, knowledge_context = 1_500, reflection_context = 500.
        300 chars of reflection is well under 500-token budget (~75 tokens).
        1_800 chars of knowledge is well under 1_500-token budget (~450 tokens).
        """
        mgr = self._make_manager()
        knowledge_text = "K" * 1_800
        reflection_text = "R" * 300

        mgr.set_knowledge_context(knowledge_text)
        mgr.set_reflection_context(reflection_text)

        snapshot = mgr.prepare_context(purpose="test")

        # Find the reflection and knowledge sections by name
        section_map = {s.name: s for s in snapshot.sections}

        assert "reflection" in section_map, "reflection section missing from snapshot"
        assert "knowledge" in section_map, "knowledge section missing from snapshot"

        # Both contents must survive intact (no truncation)
        assert section_map["reflection"].content == reflection_text, (
            "reflection content was truncated unexpectedly"
        )
        assert section_map["knowledge"].content == knowledge_text, (
            "knowledge content was truncated unexpectedly"
        )

    def test_oversized_reflection_is_truncated_to_budget(self):
        """Inject a reflection prompt whose token count exceeds 500;
        assert it is truncated to fit within the reflection_context budget.

        600 tokens ≈ 2_400 chars (4 chars/token approximation).
        We inject 2_600 chars to reliably exceed 500 tokens, then confirm
        the stored content is shorter than the original.
        """
        mgr = self._make_manager()
        # ~650 tokens of content (4 chars per token → 2_600 chars)
        long_reflection = "W" * 2_600

        mgr.set_reflection_context(long_reflection)

        snapshot = mgr.prepare_context(purpose="test")
        section_map = {s.name: s for s in snapshot.sections}

        assert "reflection" in section_map, "reflection section missing from snapshot"
        stored = section_map["reflection"].content

        # Stored content must be shorter than original (truncation applied)
        assert len(stored) < len(long_reflection), (
            "reflection content was not truncated despite exceeding 500-token budget"
        )
        # And the stored content must be non-empty
        assert len(stored) > 0, "reflection content was truncated to empty"

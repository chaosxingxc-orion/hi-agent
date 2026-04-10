"""Unified memory retriever across short/mid/long-term tiers.

Loading order (long -> mid -> short):
1. Long-term: Search graph for relevant knowledge (on-demand)
2. Mid-term: Load recent daily summaries for context
3. Short-term: Load current/recent session summaries

Budget-aware: allocates tokens across tiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hi_agent.memory.long_term import LongTermMemoryGraph
from hi_agent.memory.mid_term import MidTermMemoryStore
from hi_agent.memory.short_term import ShortTermMemoryStore


@dataclass
class MemoryContext:
    """Assembled memory context for LLM injection."""

    long_term_items: list[str] = field(default_factory=list)
    mid_term_items: list[str] = field(default_factory=list)
    short_term_items: list[str] = field(default_factory=list)
    total_tokens: int = 0

    def to_context_string(self) -> str:
        """Format all memory tiers as a single context string."""
        sections: list[str] = []
        if self.long_term_items:
            sections.append("=== Long-term Knowledge ===")
            sections.extend(self.long_term_items)
        if self.mid_term_items:
            sections.append("=== Recent Daily Context ===")
            sections.extend(self.mid_term_items)
        if self.short_term_items:
            sections.append("=== Current Session ===")
            sections.extend(self.short_term_items)
        return "\n".join(sections)

    def to_sections(self) -> dict[str, str]:
        """Return as dict with tier keys."""
        return {
            "long_term": "\n".join(self.long_term_items),
            "mid_term": "\n".join(self.mid_term_items),
            "short_term": "\n".join(self.short_term_items),
        }


class UnifiedMemoryRetriever:
    """Retrieve relevant memories across all three tiers."""

    def __init__(
        self,
        short_term: ShortTermMemoryStore | None = None,
        mid_term: MidTermMemoryStore | None = None,
        long_term: LongTermMemoryGraph | None = None,
        budget_tokens: int = 2000,
    ) -> None:
        """Initialize UnifiedMemoryRetriever."""
        self._short_term = short_term
        self._mid_term = mid_term
        self._long_term = long_term
        self._budget_tokens = budget_tokens

    def retrieve(
        self,
        query: str,
        task_family: str = "",
        budget_tokens: int | None = None,
    ) -> MemoryContext:
        """Retrieve relevant memories across all tiers.

        Budget allocation:
        - Long-term: 40% (structured knowledge, most valuable)
        - Mid-term: 30% (recent daily context)
        - Short-term: 30% (current session awareness)
        """
        budget = budget_tokens or self._budget_tokens
        lt_budget = int(budget * 0.4)
        mt_budget = int(budget * 0.3)
        st_budget = int(budget * 0.3)

        context = MemoryContext()
        used_tokens = 0

        # 1. Long-term: search graph
        if self._long_term is not None and query.strip():
            nodes = self._long_term.search(query, limit=10)
            remaining_chars = lt_budget * 4
            for node in nodes:
                snippet = f"[{node.node_type}] {node.content}"
                if len(snippet) > remaining_chars:
                    break
                context.long_term_items.append(snippet)
                self._long_term.record_access(node.node_id)
                remaining_chars -= len(snippet)
                used_tokens += len(snippet) // 4

        # 2. Mid-term: recent daily summaries
        if self._mid_term is not None:
            summaries = self._mid_term.list_recent(days=3)
            remaining_chars = mt_budget * 4
            for summary in summaries:
                snippet = summary.to_context_string(max_tokens=remaining_chars // 4)
                if len(snippet) > remaining_chars:
                    break
                context.mid_term_items.append(snippet)
                remaining_chars -= len(snippet)
                used_tokens += len(snippet) // 4

        # 3. Short-term: recent sessions
        if self._short_term is not None:
            memories = self._short_term.list_recent(limit=3)
            remaining_chars = st_budget * 4
            for mem in memories:
                snippet = mem.to_context_string(max_tokens=remaining_chars // 4)
                if len(snippet) > remaining_chars:
                    break
                context.short_term_items.append(snippet)
                remaining_chars -= len(snippet)
                used_tokens += len(snippet) // 4

        context.total_tokens = used_tokens
        return context

    def retrieve_for_stage(
        self,
        stage_id: str,
        task_family: str = "",
        current_failures: list[str] | None = None,
        budget_tokens: int | None = None,
    ) -> MemoryContext:
        """Stage-aware retrieval: prioritize relevant knowledge for current stage.

        When failures are present, boost long-term budget to find
        relevant past knowledge about those failure modes.
        """
        budget = budget_tokens or self._budget_tokens

        # Build query from stage + failures
        query_parts = [stage_id]
        if task_family:
            query_parts.append(task_family)
        if current_failures:
            query_parts.extend(current_failures)
            # Boost long-term when failures present
            return self._retrieve_with_failure_boost(
                query=" ".join(query_parts),
                task_family=task_family,
                budget=budget,
            )

        return self.retrieve(
            query=" ".join(query_parts),
            task_family=task_family,
            budget_tokens=budget,
        )

    def _retrieve_with_failure_boost(
        self,
        query: str,
        task_family: str,
        budget: int,
    ) -> MemoryContext:
        """Retrieve with boosted long-term budget for failure analysis.

        Budget reallocation when failures present:
        - Long-term: 60% (need past knowledge about failures)
        - Mid-term: 25%
        - Short-term: 15%
        """
        lt_budget = int(budget * 0.6)
        mt_budget = int(budget * 0.25)
        st_budget = int(budget * 0.15)

        context = MemoryContext()
        used_tokens = 0

        # 1. Long-term with boosted budget
        if self._long_term is not None and query.strip():
            nodes = self._long_term.search(query, limit=15)
            remaining_chars = lt_budget * 4
            for node in nodes:
                snippet = f"[{node.node_type}] {node.content}"
                if len(snippet) > remaining_chars:
                    break
                context.long_term_items.append(snippet)
                self._long_term.record_access(node.node_id)
                remaining_chars -= len(snippet)
                used_tokens += len(snippet) // 4

        # 2. Mid-term
        if self._mid_term is not None:
            summaries = self._mid_term.list_recent(days=3)
            remaining_chars = mt_budget * 4
            for summary in summaries:
                snippet = summary.to_context_string(max_tokens=remaining_chars // 4)
                if len(snippet) > remaining_chars:
                    break
                context.mid_term_items.append(snippet)
                remaining_chars -= len(snippet)
                used_tokens += len(snippet) // 4

        # 3. Short-term
        if self._short_term is not None:
            memories = self._short_term.list_recent(limit=2)
            remaining_chars = st_budget * 4
            for mem in memories:
                snippet = mem.to_context_string(max_tokens=remaining_chars // 4)
                if len(snippet) > remaining_chars:
                    break
                context.short_term_items.append(snippet)
                remaining_chars -= len(snippet)
                used_tokens += len(snippet) // 4

        context.total_tokens = used_tokens
        return context

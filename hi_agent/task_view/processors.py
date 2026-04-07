"""Context processor chain for Task View assembly.

Inspired by agent-core's ContextEngine pattern:
processors run in sequence, each transforming the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TaskViewContext:
    """Mutable context passed through processor chain."""

    contract_summary: str = ""
    stage_state: str = ""
    branch_state: str = ""
    evidence: list[str] = field(default_factory=list)
    memory_snippets: list[str] = field(default_factory=list)
    knowledge_snippets: list[str] = field(default_factory=list)
    episodic_snippets: list[str] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = 8192
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ContextProcessor(Protocol):
    """A single step in the context processing pipeline."""

    def process(self, context: TaskViewContext) -> TaskViewContext:
        """Transform *context* and return it (may mutate in place)."""
        ...


# ---------------------------------------------------------------------------
# Token estimation helper
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return max(1, len(text) // 4)


def _estimate_list_tokens(items: list[str]) -> int:
    """Estimate total tokens across a list of strings."""
    return sum(_estimate_tokens(s) for s in items)


# ---------------------------------------------------------------------------
# Concrete processors
# ---------------------------------------------------------------------------


class WindowLimitProcessor:
    """Trim context to fit within token window.

    Trims list fields (evidence, memory, knowledge, episodic) from the
    tail when total tokens exceed *max_tokens*.  Structural fields
    (contract_summary, stage_state, branch_state) are never trimmed.
    """

    def __init__(self, max_tokens: int = 8192) -> None:
        self._max_tokens = max_tokens

    def process(self, context: TaskViewContext) -> TaskViewContext:
        context.budget_tokens = self._max_tokens

        # Calculate structural (non-trimmable) cost.
        structural = (
            _estimate_tokens(context.contract_summary)
            + _estimate_tokens(context.stage_state)
            + _estimate_tokens(context.branch_state)
        )

        remaining = self._max_tokens - structural
        if remaining <= 0:
            # Only structural fits -- clear all lists.
            context.evidence = []
            context.memory_snippets = []
            context.knowledge_snippets = []
            context.episodic_snippets = []
            context.total_tokens = structural
            return context

        # Trim lists in reverse priority (episodic first, evidence last).
        trimmable_fields: list[str] = [
            "episodic_snippets",
            "knowledge_snippets",
            "memory_snippets",
            "evidence",
        ]

        for field_name in trimmable_fields:
            items: list[str] = getattr(context, field_name)
            kept: list[str] = []
            used = 0
            for item in items:
                cost = _estimate_tokens(item)
                if used + cost <= remaining:
                    kept.append(item)
                    used += cost
                else:
                    break
            setattr(context, field_name, kept)
            remaining -= _estimate_list_tokens(kept)

        context.total_tokens = self._max_tokens - max(remaining, 0)
        return context


class CompressionProcessor:
    """Compress verbose context sections using summarization.

    When a list field exceeds *threshold_tokens*, the processor
    truncates each item to keep the total under the threshold.
    Real implementations would call an LLM for summarization;
    this version uses simple truncation as a zero-dependency baseline.
    """

    def __init__(self, threshold_tokens: int = 4096) -> None:
        self._threshold = threshold_tokens

    def process(self, context: TaskViewContext) -> TaskViewContext:
        for field_name in ("evidence", "memory_snippets", "knowledge_snippets", "episodic_snippets"):
            items: list[str] = getattr(context, field_name)
            total = _estimate_list_tokens(items)
            if total <= self._threshold:
                continue
            # Truncate each item proportionally.
            compressed: list[str] = []
            per_item_budget = max(1, (self._threshold * 4) // max(len(items), 1))
            for item in items:
                compressed.append(item[:per_item_budget])
            setattr(context, field_name, compressed)
        return context


class EvidencePriorityProcessor:
    """Ensure evidence has highest priority in budget allocation.

    Moves evidence items to the front of the budget consideration:
    if total context exceeds budget, trim other sections before evidence.
    """

    def process(self, context: TaskViewContext) -> TaskViewContext:
        budget = context.budget_tokens
        structural = (
            _estimate_tokens(context.contract_summary)
            + _estimate_tokens(context.stage_state)
            + _estimate_tokens(context.branch_state)
        )
        remaining = budget - structural
        if remaining <= 0:
            return context

        # Reserve up to 50% of remaining budget for evidence.
        evidence_budget = remaining // 2
        other_budget = remaining - evidence_budget

        # Trim evidence to its budget.
        evidence_kept: list[str] = []
        used = 0
        for item in context.evidence:
            cost = _estimate_tokens(item)
            if used + cost <= evidence_budget:
                evidence_kept.append(item)
                used += cost
            else:
                break
        context.evidence = evidence_kept
        evidence_used = used

        # Redistribute unused evidence budget to others.
        actual_other_budget = other_budget + (evidence_budget - evidence_used)

        # Trim other fields with shared budget.
        for field_name in ("memory_snippets", "knowledge_snippets", "episodic_snippets"):
            items: list[str] = getattr(context, field_name)
            kept: list[str] = []
            field_used = 0
            for item in items:
                cost = _estimate_tokens(item)
                if field_used + cost <= actual_other_budget:
                    kept.append(item)
                    field_used += cost
                else:
                    break
            setattr(context, field_name, kept)
            actual_other_budget -= field_used

        context.total_tokens = budget - max(actual_other_budget, 0) - (evidence_budget - evidence_used)
        return context


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


class ContextProcessorChain:
    """Execute processors in sequence."""

    def __init__(self, processors: list[ContextProcessor] | None = None) -> None:
        self._processors: list[ContextProcessor] = list(processors) if processors else []

    def add(self, processor: ContextProcessor) -> ContextProcessorChain:
        """Append a processor and return *self* for chaining."""
        self._processors.append(processor)
        return self

    def execute(self, context: TaskViewContext) -> TaskViewContext:
        """Run all processors in sequence on *context*."""
        for proc in self._processors:
            context = proc.process(context)
        return context

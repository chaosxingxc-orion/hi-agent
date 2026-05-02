"""Knowledge granularity levels for retrieval.

Four levels, each for different use cases:
  Level 1 - Fact:     ~20-50 tokens. Atomic assertion.
  Level 2 - Chunk:    ~100-300 tokens. Fact + context + source.
  Level 3 - Page:     ~500-2000 tokens. Full topic coverage.
  Level 4 - Subgraph: ~200-800 tokens serialized. Entity network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# W31 T-24' decision: value object passed to L3 store which carries tenant_id; tenant-agnostic.
# scope: process-internal
@dataclass
class KnowledgeItem:
    """A single retrievable knowledge item at a specific granularity."""

    item_id: str
    content: str
    level: int  # 1=fact, 2=chunk, 3=page, 4=subgraph
    source_type: str  # "short_term", "mid_term", "long_term_text", "long_term_graph"
    source_id: str = ""
    relevance_score: float = 0.0
    recency_score: float = 0.0
    importance_score: float = 0.0
    composite_score: float = 0.0
    token_estimate: int = 0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (chars / 4 heuristic)."""
    return max(1, len(text) // 4)


def extract_facts(text: str, max_facts: int = 10) -> list[str]:
    """Extract atomic facts (Level 1) from a longer text.

    Split by sentences, filter short/trivial ones.
    """
    sentences: list[str] = []
    for part in text.replace("\n", ". ").split(". "):
        part = part.strip()
        if len(part) > 15:  # skip trivial fragments
            sentences.append(part)
    return sentences[:max_facts]


def to_chunk(fact: str, context: str = "", source: str = "") -> str:
    """Promote a fact (Level 1) to a chunk (Level 2) by adding context."""
    parts = [fact]
    if context:
        parts.append(f"Context: {context}")
    if source:
        parts.append(f"(Source: {source})")
    return " ".join(parts)

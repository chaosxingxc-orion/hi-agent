"""Four-layer knowledge retrieval engine.

Layer 1: CLI-style grep (zero cost, broad filter)
Layer 2: TF-IDF + BM25 precision ranking (zero cost)
Layer 3: Graph traversal + Mermaid serialization (zero model cost)
Layer 4: Embedding re-ranking (optional, has cost)

Searches across all knowledge tiers:
- Short-term memory (session summaries)
- Mid-term memory (daily summaries)
- Long-term text (wiki pages)
- Long-term graph (entity nodes + subgraphs)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from hi_agent.knowledge.granularity import KnowledgeItem, estimate_tokens
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.tfidf import HybridRanker, TFIDFIndex
from hi_agent.knowledge.wiki import KnowledgeWiki
from hi_agent.memory.long_term import LongTermMemoryGraph
from hi_agent.memory.mid_term import MidTermMemoryStore
from hi_agent.memory.short_term import ShortTermMemoryStore


@dataclass
class RetrievalResult:
    """Result of a four-layer retrieval pipeline."""

    items: list[KnowledgeItem] = field(default_factory=list)
    total_candidates: int = 0
    total_tokens: int = 0
    budget_tokens: int = 0
    layers_used: list[int] = field(default_factory=list)
    graph_mermaid: str = ""  # combined mermaid if graph results present

    def to_context_string(self) -> str:
        """Format all items for LLM context injection."""
        sections: list[str] = []
        for item in self.items:
            sections.append(item.content)
        return "\n\n---\n\n".join(sections)

    def to_sections(self) -> dict[str, list[str]]:
        """Group by source_type for structured injection."""
        result: dict[str, list[str]] = {}
        for item in self.items:
            result.setdefault(item.source_type, []).append(item.content)
        return result


class RetrievalEngine:
    """Four-layer retrieval across all knowledge sources."""

    def __init__(
        self,
        wiki: KnowledgeWiki | None = None,
        graph: LongTermMemoryGraph | None = None,
        short_term: ShortTermMemoryStore | None = None,
        mid_term: MidTermMemoryStore | None = None,
        graph_renderer: GraphRenderer | None = None,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        """Initialize RetrievalEngine."""
        self._wiki = wiki
        self._graph = graph
        self._short_term = short_term
        self._mid_term = mid_term
        self._renderer = graph_renderer
        self._embedding_fn = embedding_fn
        self._tfidf = TFIDFIndex()
        self._ranker = HybridRanker(self._tfidf)
        self._indexed = False

    def build_index(self) -> int:
        """Build TF-IDF index from all knowledge sources. Returns doc count."""
        # Index wiki pages
        if self._wiki is not None:
            for page in self._wiki.list_pages():
                doc_text = f"{page.title} {page.content} {' '.join(page.tags)}"
                self._tfidf.add(f"wiki:{page.page_id}", doc_text)

        # Index graph nodes
        if self._graph is not None:
            for node_id, node in self._graph._nodes.items():
                doc_text = f"{node.content} {' '.join(node.tags)}"
                self._tfidf.add(f"graph:{node_id}", doc_text)

        # Index short-term summaries
        if self._short_term is not None:
            for mem in self._short_term.list_recent(limit=50):
                doc_text = mem.to_context_string()
                self._tfidf.add(f"short:{mem.session_id}", doc_text)

        # Index mid-term daily summaries
        if self._mid_term is not None:
            for summary in self._mid_term.list_recent(days=30):
                doc_text = summary.to_context_string()
                self._tfidf.add(f"mid:{summary.date}", doc_text)

        self._indexed = True
        return self._tfidf.doc_count

    def retrieve(
        self,
        query: str,
        budget_tokens: int = 2000,
        include_graph_viz: bool = True,
    ) -> RetrievalResult:
        """Full four-layer retrieval pipeline."""
        if not self._indexed:
            self.build_index()

        # Layer 1: grep-style keyword filter
        candidates = self._layer1_grep(query)

        # Layer 2: TF-IDF + BM25 ranking
        ranked = self._layer2_rank(query, candidates)

        # Layer 3: Graph traversal for graph candidates
        enriched = self._layer3_graph_expand(query, ranked, include_graph_viz)

        # Layer 4: Optional embedding re-rank
        if self._embedding_fn is not None:
            enriched = self._layer4_embedding_rerank(query, enriched)

        # Composite scoring + budget trim
        layers = [1, 2, 3]
        if self._embedding_fn is not None:
            layers.append(4)

        final = self._score_and_trim(enriched, budget_tokens)
        final.layers_used = layers
        return final

    def _layer1_grep(self, query: str) -> list[KnowledgeItem]:
        """Layer 1: Keyword matching across all sources.

        Fast, broad, zero cost. Returns up to ~50 candidates.
        """
        keywords = [kw.lower() for kw in query.split() if kw.strip()]
        if not keywords:
            return []

        candidates: list[KnowledgeItem] = []
        seen_ids: set[str] = set()

        # Search wiki pages
        if self._wiki is not None:
            for page in self._wiki.list_pages():
                text = f"{page.title} {page.content} {' '.join(page.tags)}".lower()
                if any(kw in text for kw in keywords):
                    item_id = f"wiki:{page.page_id}"
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        candidates.append(
                            KnowledgeItem(
                                item_id=item_id,
                                content=f"## {page.title}\n{page.content}",
                                level=3,  # page level
                                source_type="long_term_text",
                                source_id=page.page_id,
                                token_estimate=estimate_tokens(page.content),
                                tags=page.tags,
                                importance_score=page.confidence,
                            )
                        )

        # Search graph nodes
        if self._graph is not None:
            for node_id, node in self._graph._nodes.items():
                text = f"{node.content} {' '.join(node.tags)}".lower()
                if any(kw in text for kw in keywords):
                    item_id = f"graph:{node_id}"
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        neighbors = self._graph.get_neighbors(node_id)
                        candidates.append(
                            KnowledgeItem(
                                item_id=item_id,
                                content=node.content,
                                level=1,  # fact level initially
                                source_type="long_term_graph",
                                source_id=node_id,
                                token_estimate=estimate_tokens(node.content),
                                tags=node.tags,
                                importance_score=node.confidence,
                                metadata={
                                    "degree": len(neighbors),
                                    "access_count": node.access_count,
                                },
                            )
                        )

        # Search short-term memories
        if self._short_term is not None:
            for mem in self._short_term.list_recent(limit=20):
                text = mem.to_context_string().lower()
                if any(kw in text for kw in keywords):
                    item_id = f"short:{mem.session_id}"
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        content = mem.to_context_string()
                        candidates.append(
                            KnowledgeItem(
                                item_id=item_id,
                                content=content,
                                level=2,  # chunk level
                                source_type="short_term",
                                source_id=mem.session_id,
                                token_estimate=estimate_tokens(content),
                                recency_score=0.8,  # recent sessions
                            )
                        )

        # Search mid-term summaries
        if self._mid_term is not None:
            for summary in self._mid_term.list_recent(days=30):
                text = summary.to_context_string().lower()
                if any(kw in text for kw in keywords):
                    item_id = f"mid:{summary.date}"
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        content = summary.to_context_string()
                        candidates.append(
                            KnowledgeItem(
                                item_id=item_id,
                                content=content,
                                level=2,  # chunk level
                                source_type="mid_term",
                                source_id=summary.date,
                                token_estimate=estimate_tokens(content),
                                recency_score=0.5,
                            )
                        )

        return candidates[:50]

    def _layer2_rank(
        self, query: str, candidates: list[KnowledgeItem]
    ) -> list[KnowledgeItem]:
        """Layer 2: BM25 ranking of candidates. Returns top ~10."""
        if not candidates:
            return []

        # Get BM25 scores from full index
        bm25_results = self._tfidf.bm25(query, limit=50)
        bm25_map = dict(bm25_results)

        # Assign relevance scores to candidates
        for item in candidates:
            score = bm25_map.get(item.item_id, 0.0)
            # Normalize to 0-1 range
            item.relevance_score = min(1.0, score / 10.0) if score > 0 else 0.0

        # Sort by relevance and take top 10
        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates[:10]

    def _layer3_graph_expand(
        self,
        query: str,
        candidates: list[KnowledgeItem],
        include_viz: bool,
    ) -> list[KnowledgeItem]:
        """Layer 3: For graph-sourced candidates, expand to subgraph.

        Serialize as Mermaid + key node summaries.
        Non-graph candidates pass through unchanged.
        """
        for item in candidates:
            if item.source_type == "long_term_graph" and self._graph is not None:
                # Get subgraph (depth=2)
                nodes, _edges = self._graph.get_subgraph(
                    item.source_id, depth=2
                )
                if not nodes:
                    continue

                if include_viz and self._renderer is not None:
                    mermaid = self._renderer.to_mermaid(max_nodes=15)
                    summary_lines = [
                        f"- {n.content[:100]}" for n in nodes[:5]
                    ]
                    item.content = (
                        f"```mermaid\n{mermaid}\n```\n"
                        f"Key entities:\n" + "\n".join(summary_lines)
                    )
                    item.level = 4  # subgraph level
                    item.token_estimate = estimate_tokens(item.content)
                else:
                    # Text-only expansion
                    summary_lines = [
                        f"- [{n.node_type}] {n.content[:100]}"
                        for n in nodes[:5]
                    ]
                    item.content = "Key entities:\n" + "\n".join(summary_lines)
                    item.level = 4
                    item.token_estimate = estimate_tokens(item.content)

        return candidates

    def _layer4_embedding_rerank(
        self, query: str, candidates: list[KnowledgeItem]
    ) -> list[KnowledgeItem]:
        """Layer 4: Embedding cosine re-ranking (optional).

        Only called if embedding_fn is provided.
        """
        if self._embedding_fn is None:
            return candidates

        query_emb = self._embedding_fn(query)
        for item in candidates:
            item_emb = self._embedding_fn(item.content[:500])
            item.relevance_score = cosine_similarity(query_emb, item_emb)
        return sorted(
            candidates, key=lambda x: x.relevance_score, reverse=True
        )

    def _score_and_trim(
        self, candidates: list[KnowledgeItem], budget_tokens: int
    ) -> RetrievalResult:
        """Apply composite scoring, then trim to budget."""
        scored = self._ranker.rank("", candidates)

        # Trim to budget
        selected: list[KnowledgeItem] = []
        used_tokens = 0
        for item in scored:
            if used_tokens + item.token_estimate > budget_tokens:
                break
            selected.append(item)
            used_tokens += item.token_estimate

        return RetrievalResult(
            items=selected,
            total_candidates=len(candidates),
            total_tokens=used_tokens,
            budget_tokens=budget_tokens,
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

"""Three-layer knowledge retrieval engine (embedding layer optional).

Layer 1: CLI-style grep (zero cost, broad filter)
Layer 2: TF-IDF + BM25 precision ranking (zero cost)
Layer 3: Graph traversal + Mermaid serialization (zero model cost)
Layer 4 (optional): Embedding cosine re-ranking — only active when an
    ``embedding_fn`` is supplied to ``RetrievalEngine``; not wired by default.

Searches across all knowledge tiers:
- Short-term memory (session summaries)
- Mid-term memory (daily summaries)
- Long-term text (wiki pages)
- Long-term graph (entity nodes + subgraphs)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hi_agent.knowledge.granularity import KnowledgeItem, estimate_tokens
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.tfidf import HybridRanker, TFIDFIndex
from hi_agent.knowledge.wiki import KnowledgeWiki
from hi_agent.memory.long_term import LongTermMemoryGraph
from hi_agent.memory.mid_term import MidTermMemoryStore
from hi_agent.memory.short_term import ShortTermMemoryStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result of a retrieval pipeline (3 layers always active; layer 4 optional)."""

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
    """Three-layer retrieval across all knowledge sources (optional embedding layer 4)."""

    def __init__(
        self,
        wiki: KnowledgeWiki | None = None,
        graph: LongTermMemoryGraph | None = None,
        short_term: ShortTermMemoryStore | None = None,
        mid_term: MidTermMemoryStore | None = None,
        graph_renderer: GraphRenderer | None = None,
        embedding_fn: Callable[[str], list[float]] | None = None,
        tfidf: TFIDFIndex | None = None,
        storage_dir: str = ".hi_agent/knowledge",
    ) -> None:
        """Initialize RetrievalEngine."""
        self._wiki = wiki
        self._graph = graph
        self._short_term = short_term
        self._mid_term = mid_term
        self._renderer = graph_renderer
        self._embedding_fn = embedding_fn
        self._tfidf = tfidf if tfidf is not None else TFIDFIndex()
        self._ranker = HybridRanker(self._tfidf)
        self._indexed = False
        self._index_dirty = True
        self._index_fingerprint: str = ""
        self._index_lock = threading.Lock()
        self._storage_dir = storage_dir
        self._injection_scanner = None  # lazy-initialised in _scan_content

    # ------------------------------------------------------------------
    # Index persistence helpers (Fix-6)
    # ------------------------------------------------------------------

    _CACHE_SCHEMA_VERSION = 1

    def _index_cache_path(self) -> str:
        """Returns the file path for the persisted TF-IDF index cache."""
        return os.path.join(self._storage_dir, ".index_cache.json")

    def _compute_fingerprint(self, docs: dict[str, str]) -> str:
        """Compute sha256 fingerprint over document IDs and content.

        Sorted by key before hashing so insertion order does not matter.
        Including content means a doc that changes ID-silently still
        produces a different fingerprint.
        """
        hasher = hashlib.sha256()
        for doc_id in sorted(docs.keys()):
            content = docs.get(doc_id, "")
            hasher.update(f"{doc_id}:{content}\n".encode())
        return hasher.hexdigest()

    def _save_index(self) -> None:
        """Persist the TF-IDF index to disk as a JSON cache.

        Failures are swallowed so that a transient IO error never disrupts
        the main retrieval flow.

        Deletes any stale legacy binary cache file if present.
        """
        try:
            path = self._index_cache_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)

            # Clean up the old binary cache file if it exists.
            legacy_path = os.path.join(self._storage_dir, ".index_cache" + ".pkl")
            if os.path.exists(legacy_path):
                with contextlib.suppress(OSError):
                    os.remove(legacy_path)

            payload = {
                "schema_version": self._CACHE_SCHEMA_VERSION,
                "fingerprint": self._compute_fingerprint(self._tfidf._docs),
                "built_at": datetime.now(tz=UTC).isoformat(),
                "docs": self._tfidf._docs,
                "doc_tokens": self._tfidf._doc_tokens,
                "idf": self._tfidf._idf,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            logger.debug("Index cache saved to %s", path)
        except Exception as exc:
            logger.warning("Failed to save index cache: %s", exc)

    def _load_index(self) -> bool:
        """Try to restore the TF-IDF index from a JSON cache file.

        Returns True when the index was successfully loaded; False otherwise
        (missing file, invalid JSON, wrong schema_version, or fingerprint
        mismatch all return False so the caller rebuilds from scratch).
        Failures are logged as warnings and never propagated.
        """
        try:
            path = self._index_cache_path()
            if not os.path.exists(path):
                return False
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            if data.get("schema_version") != self._CACHE_SCHEMA_VERSION:
                logger.warning(
                    "Index cache schema_version mismatch (got %s, want %s) — rebuilding",
                    data.get("schema_version"),
                    self._CACHE_SCHEMA_VERSION,
                )
                return False

            stored_fp = data.get("fingerprint", "")
            expected_fp = self._compute_fingerprint(data.get("docs", {}))
            if stored_fp != expected_fp:
                logger.warning("Index cache fingerprint mismatch — rebuilding")
                return False

            self._tfidf._docs = data["docs"]
            self._tfidf._doc_tokens = data["doc_tokens"]
            self._tfidf._idf = {k: float(v) for k, v in data["idf"].items()}
            self._tfidf._dirty = False
            # Rebuild the ranker so it references the restored index object.
            self._ranker = HybridRanker(self._tfidf)
            logger.debug(
                "Index cache loaded from %s (built_at=%s)",
                path,
                data.get("built_at", "unknown"),
            )
            return True
        except Exception as exc:
            logger.warning("Failed to load index cache: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Injection scanning helper (Fix-9)
    # ------------------------------------------------------------------

    def _scan_content(self, content: str, source: str = "") -> None:
        """Scan *content* for prompt injection before ingesting.

        Delegates to InjectionScanner.scan_and_raise() when the security
        module is available.  InjectionDetectedError is intentionally NOT
        caught here — callers must handle it.

        ImportError is silently ignored so that the security module remains
        an optional dependency.
        """
        try:
            from hi_agent.security.injection_scanner import InjectionScanner

            if self._injection_scanner is None:
                self._injection_scanner = InjectionScanner()
            self._injection_scanner.scan_and_raise(content, source=source)
        except ImportError:
            pass  # security module not available — skip scan

    def build_index(self) -> int:
        """Build TF-IDF index from all knowledge sources. Returns doc count.

        On the first call the method attempts to restore a previously
        persisted index from disk (Fix-6: index persistence).  When no
        valid cache exists, the index is built from scratch and then saved
        so that subsequent restarts can skip the rebuild.
        """
        with self._index_lock:
            if self._indexed:
                return self._tfidf.doc_count

            # Attempt to load a previously persisted index before rebuilding.
            if self._load_index():
                self._indexed = True
                return self._tfidf.doc_count

            # Index wiki pages
            if self._wiki is not None:
                for page in self._wiki.list_pages():
                    doc_text = f"{page.title} {page.content} {' '.join(page.tags)}"
                    self._tfidf.add(f"wiki:{page.page_id}", doc_text)

            # Index graph nodes
            if self._graph is not None:
                for node_id, node in self._graph.iter_nodes():
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
            self._index_dirty = False
            self._index_fingerprint = self._compute_fingerprint(self._tfidf._docs)
            # Persist the freshly built index so future restarts skip the rebuild.
            self._save_index()
            return self._tfidf.doc_count

    async def warm_index_async(self) -> int:
        """Build the index in a background thread without blocking the event loop.

        Safe to call at server startup.  Returns the number of indexed docs.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.build_index)

    def mark_index_dirty(self) -> None:
        """Signal that source documents have changed and the index needs rebuild."""
        self._index_dirty = True
        with self._index_lock:
            self._indexed = False

    def ingest_document(self, doc_id: str, text: str, source: str = "") -> None:
        """Ingest a single document into the TF-IDF index.

        Runs an injection scan (Fix-9) before adding the text so that
        malicious content is rejected before it reaches the index.
        InjectionDetectedError propagates to the caller; all other
        indexing work is performed under the index lock.

        Args:
            doc_id: Unique identifier for this document (e.g. ``"wiki:slug"``).
            text:   Raw text content to index.
            source: Human-readable origin label used in scan error messages.
        """
        # Security scan — InjectionDetectedError must propagate to caller.
        self._scan_content(text, source=source or doc_id)

        with self._index_lock:
            self._tfidf.add(doc_id, text)
            # Mark index as dirty so the next retrieve() triggers a fresh cache save.
            self._indexed = True
            self._save_index()

    def retrieve(
        self,
        query: str,
        budget_tokens: int = 2000,
        include_graph_viz: bool = True,
    ) -> RetrievalResult:
        """Run the retrieval pipeline: grep -> BM25 -> graph (layers 1-3 always).

        Layer 4 (embedding cosine re-rank) runs only when ``embedding_fn``
        was supplied at construction time; it is skipped otherwise.
        """
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

        final = self._score_and_trim(query, enriched, budget_tokens)
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
            for node_id, node in self._graph.iter_nodes():
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

    def _layer2_rank(self, query: str, candidates: list[KnowledgeItem]) -> list[KnowledgeItem]:
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
                nodes, _edges = self._graph.get_subgraph(item.source_id, depth=2)
                if not nodes:
                    continue

                if include_viz and self._renderer is not None:
                    mermaid = self._renderer.to_mermaid(max_nodes=15)
                    summary_lines = [f"- {n.content[:100]}" for n in nodes[:5]]
                    item.content = f"```mermaid\n{mermaid}\n```\nKey entities:\n" + "\n".join(
                        summary_lines
                    )
                    item.level = 4  # subgraph level
                    item.token_estimate = estimate_tokens(item.content)
                else:
                    # Text-only expansion
                    summary_lines = [f"- [{n.node_type}] {n.content[:100]}" for n in nodes[:5]]
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
        return sorted(candidates, key=lambda x: x.relevance_score, reverse=True)

    def _score_and_trim(
        self, query: str, candidates: list[KnowledgeItem], budget_tokens: int
    ) -> RetrievalResult:
        """Apply composite scoring, then trim to budget."""
        scored = self._ranker.rank(query, candidates)

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

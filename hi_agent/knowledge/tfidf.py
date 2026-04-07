"""Lightweight TF-IDF and BM25 ranking engine.

Pure Python implementation with no external dependencies.
Used for Layer 2 retrieval (zero-cost precision ranking).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from hi_agent.knowledge.granularity import KnowledgeItem

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


class TFIDFIndex:
    """In-memory TF-IDF index for fast text ranking."""

    def __init__(self) -> None:
        self._docs: dict[str, str] = {}  # doc_id -> text
        self._doc_tokens: dict[str, list[str]] = {}
        self._idf: dict[str, float] = {}
        self._dirty: bool = True

    def add(self, doc_id: str, text: str) -> None:
        """Add or update a document."""
        self._docs[doc_id] = text
        self._doc_tokens[doc_id] = self._tokenize(text)
        self._dirty = True

    def remove(self, doc_id: str) -> None:
        """Remove a document from the index."""
        self._docs.pop(doc_id, None)
        self._doc_tokens.pop(doc_id, None)
        self._dirty = True

    def _tokenize(self, text: str) -> list[str]:
        """Simple whitespace + lowering tokenizer. Strip punctuation."""
        cleaned = _PUNCT_RE.sub(" ", text.lower())
        return [tok for tok in cleaned.split() if tok]

    def _rebuild_idf(self) -> None:
        """Rebuild IDF scores from all documents."""
        N = len(self._docs)
        if N == 0:
            self._idf = {}
            self._dirty = False
            return
        df: Counter[str] = Counter()
        for tokens in self._doc_tokens.values():
            for unique_token in set(tokens):
                df[unique_token] += 1
        self._idf = {
            term: math.log((N - freq + 0.5) / (freq + 0.5) + 1)
            for term, freq in df.items()
        }
        self._dirty = False

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Search by TF-IDF cosine similarity. Returns [(doc_id, score)]."""
        if not self._docs:
            return []
        if self._dirty:
            self._rebuild_idf()

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Build query vector
        query_tf = Counter(query_tokens)
        query_vec: dict[str, float] = {}
        for term, count in query_tf.items():
            idf = self._idf.get(term, 0.0)
            query_vec[term] = count * idf

        results: list[tuple[str, float]] = []
        for doc_id, tokens in self._doc_tokens.items():
            doc_tf = Counter(tokens)
            # Compute dot product and norms
            dot = 0.0
            doc_norm_sq = 0.0
            for term, count in doc_tf.items():
                idf = self._idf.get(term, 0.0)
                tfidf = count * idf
                doc_norm_sq += tfidf * tfidf
                if term in query_vec:
                    dot += tfidf * query_vec[term]

            query_norm_sq = sum(v * v for v in query_vec.values())
            if doc_norm_sq == 0 or query_norm_sq == 0:
                continue
            score = dot / (math.sqrt(doc_norm_sq) * math.sqrt(query_norm_sq))
            if score > 0:
                results.append((doc_id, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def bm25(
        self,
        query: str,
        limit: int = 10,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> list[tuple[str, float]]:
        """Search by BM25 ranking. Returns [(doc_id, score)].

        k1: term frequency saturation. b: length normalization.
        """
        if not self._docs:
            return []
        if self._dirty:
            self._rebuild_idf()

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Average document length
        total_tokens = sum(len(t) for t in self._doc_tokens.values())
        avgdl = total_tokens / len(self._docs) if self._docs else 1.0

        results: list[tuple[str, float]] = []
        for doc_id, tokens in self._doc_tokens.items():
            dl = len(tokens)
            doc_tf = Counter(tokens)
            score = 0.0
            for qt in query_tokens:
                tf = doc_tf.get(qt, 0)
                if tf == 0:
                    continue
                idf = self._idf.get(qt, 0.0)
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / avgdl)
                score += idf * numerator / denominator
            if score > 0:
                results.append((doc_id, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    @property
    def doc_count(self) -> int:
        """Return the number of indexed documents."""
        return len(self._docs)


class HybridRanker:
    """Combine TF-IDF/BM25 text scores with structural signals.

    For graph nodes, adds bonuses for:
    - Node degree (hub nodes more important)
    - Relation relevance (edges matching query terms)
    - Access frequency (more-used knowledge ranked higher)
    """

    def __init__(self, tfidf: TFIDFIndex) -> None:
        self._tfidf = tfidf

    def rank(
        self,
        query: str,
        candidates: list[KnowledgeItem],
        *,
        recency_weight: float = 0.3,
        importance_weight: float = 0.2,
        relevance_weight: float = 0.4,
        structure_weight: float = 0.1,
    ) -> list[KnowledgeItem]:
        """Composite scoring: relevance * 0.4 + recency * 0.3 + importance * 0.2 + structure * 0.1.

        Returns sorted list with composite_score set.
        """
        # If query provided, get BM25 scores for relevance
        bm25_scores: dict[str, float] = {}
        if query:
            results = self._tfidf.bm25(query, limit=len(candidates) + 50)
            bm25_scores = dict(results)

        for item in candidates:
            # Relevance: use pre-set relevance_score or BM25
            rel = item.relevance_score
            if rel == 0.0 and item.item_id in bm25_scores:
                rel = min(1.0, bm25_scores[item.item_id] / 10.0)  # normalize
                item.relevance_score = rel

            # Structure bonus for graph items
            struct = 0.0
            if item.source_type == "long_term_graph":
                degree = item.metadata.get("degree", 0)
                access = item.metadata.get("access_count", 0)
                struct = min(1.0, (degree * 0.3 + access * 0.05))

            item.composite_score = (
                relevance_weight * rel
                + recency_weight * item.recency_score
                + importance_weight * item.importance_score
                + structure_weight * struct
            )

        candidates.sort(key=lambda x: x.composite_score, reverse=True)
        return candidates

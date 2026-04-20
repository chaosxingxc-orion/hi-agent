"""Standalone retrieval component builder (HI-W7-002)."""

from __future__ import annotations

import logging
from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.knowledge.retrieval_engine import RetrievalEngine
from hi_agent.knowledge.tfidf import TFIDFIndex

logger = logging.getLogger(__name__)


class RetrievalBuilder:
    """Builds retrieval components with constructor-time dependencies."""

    def __init__(self, config: TraceConfig) -> None:
        self._config = config

    def build_retrieval_engine(
        self,
        wiki: Any = None,
        graph: Any = None,
        short_term: Any = None,
        mid_term: Any = None,
    ) -> RetrievalEngine:
        """Build RetrievalEngine with TF-IDF and embedding callable pre-wired."""
        tfidf = TFIDFIndex()
        embedding_fn = None
        try:
            from hi_agent.knowledge.embedding import TFIDFEmbeddingProvider

            embedding_fn = TFIDFEmbeddingProvider(tfidf).as_callable()
        except Exception as exc:
            logger.debug("TF-IDF embedding provider unavailable: %s", exc)

        return RetrievalEngine(
            wiki=wiki,
            graph=graph,
            short_term=short_term,
            mid_term=mid_term,
            embedding_fn=embedding_fn,
            tfidf=tfidf,
        )

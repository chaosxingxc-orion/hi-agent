"""MemoryBuilder: capability builder for memory tier subsystem.

Extracted from SystemBuilder in W6-004.
SystemBuilder.build_short_term_store / build_mid_term_store / etc. are now facades.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.server.dream_scheduler import MemoryLifecycleManager

logger = logging.getLogger(__name__)


class MemoryBuilder:
    """Builds memory tier components.

    Takes only TraceConfig — does not hold a reference to SystemBuilder.
    """

    def __init__(self, config: TraceConfig) -> None:
        self._config = config

    def build_episodic_store(self) -> EpisodicMemoryStore:
        """Build EpisodicMemoryStore using configured storage directory."""
        return EpisodicMemoryStore(storage_dir=self._config.episodic_storage_dir)

    def build_failure_collector(self) -> FailureCollector:
        """Build a fresh FailureCollector."""
        return FailureCollector()

    def build_watchdog(self) -> ProgressWatchdog:
        """Build ProgressWatchdog with config-driven thresholds."""
        return ProgressWatchdog(
            window_size=self._config.watchdog_window_size,
            min_success_rate=self._config.watchdog_min_success_rate,
            max_consecutive_failures=self._config.watchdog_max_consecutive_failures,
        )

    def build_short_term_store(self, profile_id: str = "") -> Any:
        """Build short-term memory store, optionally scoped to a profile."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        base = self._config.episodic_storage_dir.replace("episodes", "")
        path = (
            os.path.join(base, "profiles", profile_id, "short_term")
            if profile_id
            else self._config.episodic_storage_dir.replace("episodes", "short_term")
        )
        project_id = getattr(self._config, "project_id", "")
        return ShortTermMemoryStore(path, project_id=project_id)

    def build_mid_term_store(self, profile_id: str = "") -> Any:
        """Build mid-term memory store, optionally scoped to a profile."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        base = self._config.episodic_storage_dir.replace("episodes", "")
        path = (
            os.path.join(base, "profiles", profile_id, "mid_term")
            if profile_id
            else self._config.episodic_storage_dir.replace("episodes", "mid_term")
        )
        return MidTermMemoryStore(path)

    def build_long_term_graph(self, profile_id: str = "") -> Any:
        """Build long-term memory graph, optionally scoped to a profile."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        project_id = getattr(self._config, "project_id", "")
        graph = LongTermMemoryGraph(
            self._config.episodic_storage_dir.replace(
                "episodes", "long_term/graph.json"
            ),
            profile_id=profile_id,
            project_id=project_id,
        )
        try:
            graph.load()
        except (FileNotFoundError, KeyError, ValueError):
            pass  # no prior state on first run — expected on fresh installs
        return graph

    def build_retrieval_engine(
        self,
        short_term_store: Any = None,
        mid_term_store: Any = None,
        long_term_graph: Any = None,
        profile_id: str = "",
        wiki: Any = None,
    ) -> Any:
        """Build four-layer retrieval engine across all memory tiers.

        When store objects are provided, they are used directly (no new instances
        are created). When absent, new instances are built scoped to profile_id.

        Layer 4 (semantic embedding re-ranking) is activated by wiring a
        TFIDFEmbeddingProvider against the engine's internal TFIDFIndex.
        This requires no external dependencies.  If construction fails for
        any reason the engine falls back to embedding_fn=None (Layers 1-3
        only).

        Args:
            wiki: Optional KnowledgeWiki instance. If None, one is built inline
                using the same construction logic as SystemBuilder.build_knowledge_wiki().
        """
        from hi_agent.knowledge.retrieval_engine import RetrievalEngine

        if wiki is None:
            from hi_agent.knowledge.wiki import KnowledgeWiki

            base = self._config.episodic_storage_dir.replace("episodes", "")
            wiki = KnowledgeWiki(os.path.join(base, "knowledge", "wiki"))
            try:
                wiki.load()
            except (FileNotFoundError, KeyError, ValueError):
                pass  # no prior state on first run — expected on fresh installs

        graph = long_term_graph if long_term_graph is not None else self.build_long_term_graph(profile_id=profile_id)
        short = short_term_store if short_term_store is not None else self.build_short_term_store(profile_id=profile_id)
        mid = mid_term_store if mid_term_store is not None else self.build_mid_term_store(profile_id=profile_id)

        # Build the engine first so we can access its internal _tfidf index.
        engine = RetrievalEngine(
            wiki=wiki, graph=graph, short_term=short, mid_term=mid
        )

        # Activate Layer 4 by wiring in a TF-IDF-based embedding function.
        # NOTE: engine._embedding_fn post-construction assignment stays here until W7-002.
        try:
            from hi_agent.knowledge.embedding import TFIDFEmbeddingProvider

            provider = TFIDFEmbeddingProvider(engine._tfidf)
            engine._embedding_fn = provider.as_callable()
        except Exception:
            # Graceful degradation: Layer 4 stays disabled, Layers 1-3 work normally.
            pass

        return engine

    def build_memory_lifecycle_manager(
        self,
        short_term_store: Any = None,
        mid_term_store: Any = None,
        long_term_graph: Any = None,
        profile_id: str = "",
        wiki: Any = None,
    ) -> MemoryLifecycleManager:
        """Build MemoryLifecycleManager wiring all memory tiers.

        When store objects are provided, they are used directly (no new
        instances are created), preserving profile-scoped paths built by
        the caller. When absent, fresh instances are built scoped to profile_id.

        Args:
            profile_id: Profile scope for fallback store construction. Has no
                effect when all store instances are provided explicitly.
            wiki: Optional KnowledgeWiki instance forwarded to build_retrieval_engine.
                If None, one is built inline.
        """
        short = short_term_store if short_term_store is not None else self.build_short_term_store(profile_id=profile_id)
        mid   = mid_term_store   if mid_term_store   is not None else self.build_mid_term_store(profile_id=profile_id)
        graph = long_term_graph  if long_term_graph  is not None else self.build_long_term_graph(profile_id=profile_id)
        return MemoryLifecycleManager(
            short_term_store=short,
            mid_term_store=mid,
            long_term_graph=graph,
            retrieval_engine=self.build_retrieval_engine(
                short_term_store=short,
                mid_term_store=mid,
                long_term_graph=graph,
                wiki=wiki,
            ),
        )

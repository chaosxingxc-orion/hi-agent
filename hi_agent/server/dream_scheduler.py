"""Memory lifecycle manager: creation triggers, transfer (dream+consolidation), status.

Called by:
- Runner: automatic short-term creation after each run (handled separately)
- Runner: on_run_completed() auto-triggers dream/consolidation based on intervals
- API: POST /memory/dream, POST /memory/consolidate, GET /memory/status
- Cron/manual: trigger_full_cycle()
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class MemoryLifecycleManager:
    """Manages memory transfer: short->mid (Dream) and mid->long (Consolidation)."""

    def __init__(
        self,
        short_term_store: Any | None = None,
        mid_term_store: Any | None = None,
        long_term_graph: Any | None = None,
        retrieval_engine: Any | None = None,
        auto_dream_interval: int = 5,
        auto_consolidate_interval: int = 20,
    ) -> None:
        """Initialize MemoryLifecycleManager.

        Args:
            short_term_store: Short-term memory store.
            mid_term_store: Mid-term memory store.
            long_term_graph: Long-term knowledge graph.
            retrieval_engine: Retrieval engine for index rebuilds.
            auto_dream_interval: Trigger dream every N runs (0=disabled).
            auto_consolidate_interval: Trigger LTM consolidation every N runs (0=disabled).
        """
        self._short = short_term_store
        self._mid = mid_term_store
        self._graph = long_term_graph
        self._retrieval = retrieval_engine
        self._dream = None
        self._consolidator = None
        self._lock = threading.Lock()
        self._run_count: int = 0
        self.auto_dream_interval: int = auto_dream_interval
        self.auto_consolidate_interval: int = auto_consolidate_interval
        # Lazy init
        if self._short and self._mid:
            from hi_agent.memory.mid_term import DreamConsolidator

            self._dream = DreamConsolidator(self._short, self._mid)
        if self._mid and self._graph:
            from hi_agent.memory.long_term import LongTermConsolidator

            self._consolidator = LongTermConsolidator(self._mid, self._graph)

    def trigger_dream(self, date: str | None = None) -> dict[str, Any]:
        """Transfer short-term -> mid-term. Thread-safe."""
        with self._lock:
            if self._dream is None:
                return {"status": "skipped", "reason": "stores_not_configured"}
            try:
                summary = self._dream.consolidate(date)
                return {
                    "status": "completed",
                    "date": summary.date,
                    "sessions_count": summary.sessions_count,
                    "tasks_completed": len(summary.tasks_completed),
                    "key_learnings": len(summary.key_learnings),
                    "patterns_observed": len(summary.patterns_observed),
                }
            except Exception as e:
                return {"status": "error", "reason": str(e)}

    def trigger_consolidation(self, days: int = 7) -> dict[str, Any]:
        """Transfer mid-term -> long-term graph. Thread-safe."""
        with self._lock:
            if self._consolidator is None:
                return {"status": "skipped", "reason": "stores_not_configured"}
            try:
                nodes_affected = self._consolidator.consolidate(days)
                if self._graph:
                    self._graph.save()
                return {
                    "status": "completed",
                    "nodes_affected": nodes_affected,
                    "total_nodes": self._graph.node_count() if self._graph else 0,
                    "total_edges": self._graph.edge_count() if self._graph else 0,
                }
            except Exception as e:
                return {"status": "error", "reason": str(e)}

    def trigger_full_cycle(
        self, date: str | None = None, days: int = 7
    ) -> dict[str, Any]:
        """Run dream + consolidation in sequence."""
        dream = self.trigger_dream(date)
        consolidation = self.trigger_consolidation(days)
        return {"dream": dream, "consolidation": consolidation}

    def on_run_completed(self) -> None:
        """Called after each run completes to auto-trigger consolidation.

        Increments internal run counter and triggers dream (STM->MTM) or
        long-term consolidation (MTM->LTM) when the configured interval
        thresholds are reached.  Thread-safe.  Never raises.
        """
        with self._lock:
            self._run_count += 1
            count = self._run_count

        # Dream consolidation check
        if self.auto_dream_interval > 0 and count % self.auto_dream_interval == 0:
            try:
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                result = self.trigger_dream(today)
                logger.info("Auto dream consolidation (run %d): %s", count, result.get("status"))
            except Exception:
                logger.exception("Auto dream consolidation failed (run %d)", count)

        # Long-term consolidation check
        if self.auto_consolidate_interval > 0 and count % self.auto_consolidate_interval == 0:
            try:
                result = self.trigger_consolidation()
                logger.info("Auto LTM consolidation (run %d): %s", count, result.get("status"))
            except Exception:
                logger.exception("Auto LTM consolidation failed (run %d)", count)

    def rebuild_index(self) -> int:
        """Rebuild retrieval engine index."""
        if self._retrieval and hasattr(self._retrieval, "build_index"):
            return self._retrieval.build_index()
        return 0

    def get_status(self) -> dict[str, Any]:
        """Status of all memory tiers."""
        status: dict[str, Any] = {
            "short_term": None,
            "mid_term": None,
            "long_term": None,
        }
        try:
            if self._short:
                status["short_term"] = {"count": len(self._short.list_recent(1000))}
        except Exception:
            pass
        try:
            if self._mid:
                status["mid_term"] = {"count": len(self._mid.list_recent(365))}
        except Exception:
            pass
        try:
            if self._graph:
                status["long_term"] = {
                    "nodes": self._graph.node_count(),
                    "edges": self._graph.edge_count(),
                }
        except Exception:
            pass
        return status

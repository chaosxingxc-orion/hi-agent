"""Memory lifecycle manager: creation triggers, transfer (dream+consolidation), status.

Called by:
- Runner: automatic short-term creation after each run (handled separately)
- Runner: on_run_completed() auto-triggers dream/consolidation based on intervals
- API: POST /memory/dream, POST /memory/consolidate, GET /memory/status
- Cron/manual: trigger_full_cycle()
- Background: start()/stop() asyncio periodic scheduler loop
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from hi_agent.observability.metric_counter import Counter

logger = logging.getLogger(__name__)
_dream_scheduler_errors_total = Counter("hi_agent_dream_scheduler_errors_total")


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
        self._last_dream_at_run_count: int = -1
        self._last_consolidate_at_run_count: int = -1
        self.auto_dream_interval: int = auto_dream_interval
        self.auto_consolidate_interval: int = auto_consolidate_interval
        # Lazy init
        if self._short and self._mid:
            from hi_agent.memory.mid_term import DreamConsolidator

            self._dream = DreamConsolidator(self._short, self._mid)
        if self._mid and self._graph:
            from hi_agent.memory.long_term import LongTermConsolidator

            self._consolidator = LongTermConsolidator(self._mid, self._graph)

        # Asyncio periodic scheduler state
        self._scheduler_task: asyncio.Task | None = None  # type: ignore[type-arg]  expiry_wave: Wave 28
        self._check_interval_seconds: float = 60.0  # check once per minute

    # ------------------------------------------------------------------
    # Asyncio periodic scheduler
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background asyncio scheduler loop.

        Safe to call multiple times — subsequent calls are no-ops if the
        loop is already running.
        """
        if self._scheduler_task is not None:
            return
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "MemoryLifecycleManager scheduler started "
            "(dream_interval=%d runs, consolidate_interval=%d runs, "
            "check_interval=%.0fs)",
            self.auto_dream_interval,
            self.auto_consolidate_interval,
            self._check_interval_seconds,
        )

    async def stop(self) -> None:
        """Stop the background asyncio scheduler loop gracefully."""
        if self._scheduler_task is None:
            return
        self._scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._scheduler_task
        self._scheduler_task = None
        logger.info("MemoryLifecycleManager scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """Periodic check loop.  Runs until cancelled.

        Every ``_check_interval_seconds`` the loop reads the current run
        counter and fires dream / LTM consolidation when the configured
        thresholds have been crossed.  A single ``Exception`` does *not*
        abort the loop — errors are logged and the loop continues.
        ``asyncio.CancelledError`` propagates so that ``stop()`` works
        correctly.
        """
        while True:
            try:
                await asyncio.sleep(self._check_interval_seconds)
                await self._maybe_run_dream()
                await self._maybe_run_consolidate()
            except asyncio.CancelledError:
                # Requested shutdown — propagate so the task terminates.
                raise
            except Exception as exc:
                logger.error(
                    "MemoryLifecycleManager scheduler loop error (continuing): %s",
                    exc,
                    exc_info=True,
                )

    def notify_run_completed(self) -> None:
        """Notify the scheduler that a run has finished.

        Delegates to ``on_run_completed()`` which already contains the
        interval-threshold logic and is thread-safe.  This method exists
        as a named hook so callers don't need to know the internal name.
        """
        self.on_run_completed()

    def _should_trigger_dream(self) -> bool:
        """Return True exactly once per dream interval. Thread-safe."""
        with self._lock:
            count = self._run_count
            if (
                self.auto_dream_interval > 0
                and count > 0
                and count % self.auto_dream_interval == 0
                and count != self._last_dream_at_run_count
            ):
                self._last_dream_at_run_count = count
                return True
            return False

    def _should_trigger_consolidate(self) -> bool:
        """Return True exactly once per consolidation interval. Thread-safe."""
        with self._lock:
            count = self._run_count
            if (
                self.auto_consolidate_interval > 0
                and count > 0
                and count % self.auto_consolidate_interval == 0
                and count != self._last_consolidate_at_run_count
            ):
                self._last_consolidate_at_run_count = count
                return True
            return False

    async def _maybe_run_dream(self) -> None:
        """Trigger dream consolidation when the run-count threshold is reached.

        Uses the shared ``_run_count`` maintained by ``on_run_completed``
        so that both the periodic scheduler and direct ``on_run_completed``
        calls share a single counter and cannot double-trigger.
        """
        if self.auto_dream_interval <= 0:
            return
        if self._should_trigger_dream():
            logger.info(
                "Scheduler: auto-triggering Dream consolidation (run_count=%d)",
                self._last_dream_at_run_count,
            )
            try:
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                result = self.trigger_dream(today)
                logger.info("Scheduler: Dream consolidation result: %s", result.get("status"))
            except Exception as exc:
                _dream_scheduler_errors_total.inc()
                logger.error("Scheduler: Dream consolidation failed: %s", exc)

    async def _maybe_run_consolidate(self) -> None:
        """Trigger LTM consolidation when the run-count threshold is reached."""
        if self.auto_consolidate_interval <= 0:
            return
        if self._should_trigger_consolidate():
            logger.info(
                "Scheduler: auto-triggering LTM consolidation (run_count=%d)",
                self._last_consolidate_at_run_count,
            )
            try:
                result = self.trigger_consolidation()
                logger.info(
                    "Scheduler: LTM consolidation result: %s",
                    result.get("status"),
                )
            except Exception as exc:
                _dream_scheduler_errors_total.inc()
                logger.error("Scheduler: LTM consolidation failed: %s", exc)

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
                _dream_scheduler_errors_total.inc()
                logger.warning(
                    "trigger_dream failed",
                    extra={"error": str(e)},
                    exc_info=True,
                )
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
                _dream_scheduler_errors_total.inc()
                logger.warning(
                    "trigger_consolidation failed",
                    extra={"error": str(e)},
                    exc_info=True,
                )
                return {"status": "error", "reason": str(e)}

    def trigger_full_cycle(self, date: str | None = None, days: int = 7) -> dict[str, Any]:
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
        if self._should_trigger_dream():
            try:
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                result = self.trigger_dream(today)
                logger.info("Auto dream consolidation (run %d): %s", count, result.get("status"))
            except Exception as exc:
                _dream_scheduler_errors_total.inc()
                logger.warning(
                    "Auto dream consolidation failed (run %d)",
                    count,
                    extra={"error": str(exc), "run_count": str(count)},
                    exc_info=True,
                )

        # Long-term consolidation check
        if self._should_trigger_consolidate():
            try:
                result = self.trigger_consolidation()
                logger.info("Auto LTM consolidation (run %d): %s", count, result.get("status"))
            except Exception as exc:
                _dream_scheduler_errors_total.inc()
                logger.warning(
                    "Auto LTM consolidation failed (run %d)",
                    count,
                    extra={"error": str(exc), "run_count": str(count)},
                    exc_info=True,
                )

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
        except Exception as exc:
            _dream_scheduler_errors_total.inc()
            logger.warning(
                "Failed to query short_term memory store for status",
                extra={"error": str(exc)},
                exc_info=True,
            )
        try:
            if self._mid:
                status["mid_term"] = {"count": len(self._mid.list_recent(365))}
        except Exception as exc:
            _dream_scheduler_errors_total.inc()
            logger.warning(
                "Failed to query mid_term memory store for status",
                extra={"error": str(exc)},
                exc_info=True,
            )
        try:
            if self._graph:
                status["long_term"] = {
                    "nodes": self._graph.node_count(),
                    "edges": self._graph.edge_count(),
                }
        except Exception as exc:
            _dream_scheduler_errors_total.inc()
            logger.warning(
                "Failed to query long_term memory graph for status",
                extra={"error": str(exc)},
                exc_info=True,
            )
        return status

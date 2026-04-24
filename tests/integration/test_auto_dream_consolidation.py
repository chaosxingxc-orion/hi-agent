"""Tests for MemoryLifecycleManager auto-dream consolidation."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from hi_agent.server.dream_scheduler import MemoryLifecycleManager


class TestAutoDreamConsolidation:
    """MemoryLifecycleManager.on_run_completed() auto-trigger tests."""

    def _make_manager(
        self,
        dream_interval: int = 5,
        consolidate_interval: int = 20,
    ) -> MemoryLifecycleManager:
        return MemoryLifecycleManager(
            auto_dream_interval=dream_interval,
            auto_consolidate_interval=consolidate_interval,
        )

    def test_dream_triggers_at_interval(self):
        mgr = self._make_manager(dream_interval=3)
        mgr.trigger_dream = MagicMock(return_value={"status": "completed"})

        for _ in range(3):
            mgr.on_run_completed()

        mgr.trigger_dream.assert_called_once()

    def test_consolidation_triggers(self):
        mgr = self._make_manager(dream_interval=0, consolidate_interval=2)
        mgr.trigger_consolidation = MagicMock(return_value={"status": "completed"})

        mgr.on_run_completed()
        mgr.trigger_consolidation.assert_not_called()
        mgr.on_run_completed()
        mgr.trigger_consolidation.assert_called_once()

    def test_disabled_when_zero(self):
        mgr = self._make_manager(dream_interval=0, consolidate_interval=0)
        mgr.trigger_dream = MagicMock()
        mgr.trigger_consolidation = MagicMock()

        for _ in range(10):
            mgr.on_run_completed()

        mgr.trigger_dream.assert_not_called()
        mgr.trigger_consolidation.assert_not_called()

    def test_exception_swallowed(self):
        mgr = self._make_manager(dream_interval=1)
        mgr.trigger_dream = MagicMock(side_effect=RuntimeError("boom"))

        # Should not raise
        mgr.on_run_completed()

    def test_counter_increments(self):
        mgr = self._make_manager(dream_interval=5)
        assert mgr._run_count == 0
        mgr.on_run_completed()
        assert mgr._run_count == 1
        mgr.on_run_completed()
        assert mgr._run_count == 2

    def test_thread_safety(self):
        mgr = self._make_manager(dream_interval=100, consolidate_interval=100)
        errors = []

        def worker():
            try:
                for _ in range(50):
                    mgr.on_run_completed()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert mgr._run_count == 200

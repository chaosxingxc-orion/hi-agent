"""Unit tests for Round-3 defects D-3 and D-4.

D-3: mid_term_store must be wired into RunExecutor
D-4: L2->L3 consolidation must be auto-triggered in _finalize_run
"""

from __future__ import annotations

import contextlib
import tempfile
from unittest.mock import MagicMock

from hi_agent.contracts import TaskContract
from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_executor(**kwargs) -> RunExecutor:
    contract = TaskContract(task_id="t-cd-001", goal="test goal")
    kernel = MockKernel()
    return RunExecutor(contract=contract, kernel=kernel, **kwargs)


# ---------------------------------------------------------------------------
# D-3 Test A: RunExecutor accepts mid_term_store and stores it
# ---------------------------------------------------------------------------


class TestD3ConstructorWiring:
    """D-3 test A: mid_term_store param accepted and stored."""

    def test_mid_term_store_stored_on_executor(self):
        """Executor must expose the passed mid_term_store as an attribute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MidTermMemoryStore(storage_dir=tmpdir)
            executor = _make_executor(mid_term_store=store)
            assert executor.mid_term_store is store

    def test_mid_term_store_defaults_to_none(self):
        """When omitted, mid_term_store is None (no silent getattr fallback)."""
        executor = _make_executor()
        assert executor.mid_term_store is None


# ---------------------------------------------------------------------------
# D-3 Test B: _finalize_run saves L0 summary into mid_term_store when wired
# ---------------------------------------------------------------------------


class TestD3FinalizeSavesToMidTerm:
    """D-3 test B: _finalize_run calls mid_term_store.save() when summary available."""

    def test_save_called_when_summary_produced(self):
        """When L0Summarizer returns a DailySummary, mid_term_store.save is called."""
        store = MagicMock(spec=MidTermMemoryStore)
        executor = _make_executor(mid_term_store=store)

        # Inject a fake raw_memory with a _base_dir so the L0->L2 branch fires
        fake_summary = DailySummary(date="2026-04-15", sessions_count=1)
        fake_raw = MagicMock()
        fake_raw._base_dir = "some/path"
        executor.raw_memory = fake_raw

        # Patch L0Summarizer to return our fake summary so we test the save path

        # Directly mock the summarizer call inside _finalize_run via monkeypatching
        import unittest.mock as mock

        with mock.patch("hi_agent.memory.l0_summarizer.L0Summarizer") as mock_summarizer_cls:
            mock_summarizer_cls.return_value.summarize_run.return_value = fake_summary
            # Drive _finalize_run with minimal fake state
            executor._run_id = "run-test-001"
            executor.stage_graph = MagicMock()
            executor.stage_graph.trace_order.return_value = []
            executor.dag = {}
            executor.cts_budget = MagicMock()
            executor.cts_budget.total_actions_used = 0
            executor.failure_collector = None
            with contextlib.suppress(Exception):
                executor._finalize_run(outcome="completed")

        store.save.assert_called_once_with(fake_summary)


# ---------------------------------------------------------------------------
# D-4 Test A: RunExecutor accepts long_term_consolidator and stores it
# ---------------------------------------------------------------------------


class TestD4ConstructorWiring:
    """D-4 test A: long_term_consolidator param accepted and stored."""

    def test_long_term_consolidator_stored_on_executor(self):
        """Executor must expose the passed long_term_consolidator as an attribute."""
        mock_consolidator = MagicMock()
        executor = _make_executor(long_term_consolidator=mock_consolidator)
        assert executor.long_term_consolidator is mock_consolidator

    def test_long_term_consolidator_defaults_to_none(self):
        """When omitted, long_term_consolidator is None."""
        executor = _make_executor()
        assert executor.long_term_consolidator is None


# ---------------------------------------------------------------------------
# D-4 Test B: _finalize_run calls consolidator.consolidate() when wired
# ---------------------------------------------------------------------------


class TestD4FinalizeCallsConsolidate:
    """D-4 test B: _finalize_run calls long_term_consolidator.consolidate()."""

    def test_consolidate_called_after_finalize(self):
        """consolidate(days=1) must be called during _finalize_run."""
        mock_consolidator = MagicMock()
        executor = _make_executor(long_term_consolidator=mock_consolidator)

        executor._run_id = "run-test-002"
        executor.stage_graph = MagicMock()
        executor.stage_graph.trace_order.return_value = []
        executor.dag = {}
        executor.cts_budget = MagicMock()
        executor.cts_budget.total_actions_used = 0
        executor.failure_collector = None
        with contextlib.suppress(Exception):
            executor._finalize_run(outcome="completed")

        mock_consolidator.consolidate.assert_called_once_with(days=1)

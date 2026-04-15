"""Unit tests for round-5 defect fix G-5 in SystemBuilder.

G-5: build_retrieval_engine() created unscoped stores; F-2 isolation incomplete.
     The retrieval engine must share the same scoped store instances as the executor.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_builder(tmp_path):
    """Return a SystemBuilder with episodic_storage_dir pointing at tmp_path."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return SystemBuilder(config=cfg)


def _make_contract(profile_id: str | None = None):
    """Return a minimal TaskContract."""
    from hi_agent.contracts import TaskContract

    return TaskContract(task_id="t1", goal="test goal", profile_id=profile_id)


# ---------------------------------------------------------------------------
# G-5: retrieval engine store isolation
# ---------------------------------------------------------------------------


class TestG5RetrievalEngineStoreIsolation:
    def test_g5_retrieval_engine_shares_short_term_store_with_executor(self, tmp_path):
        """After build_executor() with a non-empty profile_id, the retrieval engine's
        _short_term._storage_dir must equal the executor's short_term_store._storage_dir.
        """
        builder = _make_builder(tmp_path)
        contract = _make_contract(profile_id="proj-share")
        executor = builder.build_executor(contract)

        executor_path = executor.short_term_store._storage_dir
        engine_path = executor.retrieval_engine._short_term._storage_dir
        assert executor_path == engine_path, (
            f"executor short_term path {executor_path!r} != "
            f"retrieval engine short_term path {engine_path!r}"
        )

    def test_g5_retrieval_engine_profile_scoped_path(self, tmp_path):
        """Two build_executor() calls with different profile_ids must produce
        retrieval engines with distinct _short_term._storage_dir values, each
        containing the respective profile_id substring.
        """
        builder = _make_builder(tmp_path)
        contract_a = _make_contract(profile_id="proj-a")
        contract_b = _make_contract(profile_id="proj-b")

        executor_a = builder.build_executor(contract_a)
        executor_b = builder.build_executor(contract_b)

        path_a = str(executor_a.retrieval_engine._short_term._storage_dir)
        path_b = str(executor_b.retrieval_engine._short_term._storage_dir)

        assert path_a != path_b, "Expected distinct paths for different profile_ids"
        assert "proj-a" in path_a, f"Expected 'proj-a' in path {path_a!r}"
        assert "proj-b" in path_b, f"Expected 'proj-b' in path {path_b!r}"

    def test_g5_reflection_prompt_visible_to_retrieval_engine(self, tmp_path):
        """A memory saved to executor.short_term_store must be visible via
        executor.retrieval_engine._short_term.list_recent().
        """
        from hi_agent.memory.short_term import ShortTermMemory

        builder = _make_builder(tmp_path)
        contract = _make_contract(profile_id="proj-x")
        executor = builder.build_executor(contract)

        executor.short_term_store.save(
            ShortTermMemory(
                session_id="test-sess",
                run_id="r1",
                task_goal="reflection hint",
                outcome="reflecting",
            )
        )

        recent = executor.retrieval_engine._short_term.list_recent(limit=10)
        goals = [m.task_goal for m in recent]
        assert any("reflection hint" in g for g in goals), (
            f"Expected 'reflection hint' in list_recent results, got: {goals!r}"
        )

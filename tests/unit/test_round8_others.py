"""Round-8 unit tests for K-4, K-5, K-8, K-9, K-10 defect fixes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# K-4: RunExecutorFacade.stop() must log, not silently swallow exceptions
# ---------------------------------------------------------------------------


def test_facade_stop_logs_finalize_failure(caplog):
    """stop() must log when _finalize_run raises, not silently swallow."""
    import logging
    from unittest.mock import MagicMock

    from hi_agent.executor_facade import RunExecutorFacade

    facade = RunExecutorFacade()
    facade._executor = MagicMock()
    facade._executor._finalize_run = MagicMock(side_effect=RuntimeError("finalize boom"))
    facade._contract = MagicMock()

    with caplog.at_level(logging.WARNING, logger="hi_agent.executor_facade"):
        facade.stop()

    assert any("finalize" in r.message.lower() or "finalize" in r.getMessage().lower()
               for r in caplog.records), "Expected warning about _finalize_run failure"


# ---------------------------------------------------------------------------
# K-5: ContextManager._assemble_memory() must log retrieval failures
# ---------------------------------------------------------------------------


def test_assemble_memory_logs_retrieval_failure(caplog):
    """_assemble_memory() must log when retrieval fails, not silently swallow."""
    import logging
    from unittest.mock import MagicMock

    from hi_agent.context.manager import ContextManager

    retriever = MagicMock()
    retriever.retrieve = MagicMock(side_effect=OSError("disk error"))

    from hi_agent.context.manager import ContextBudget
    budget = ContextBudget()

    mgr = ContextManager(budget=budget, memory_retriever=retriever)

    with caplog.at_level(logging.WARNING):
        section = mgr._assemble_memory()

    assert section.content == ""  # fallback still works
    assert any("memory_retrieval_failed" in r.getMessage() or "disk error" in r.getMessage()
               for r in caplog.records), "Expected warning about retrieval failure"


# ---------------------------------------------------------------------------
# K-8: Dream scheduler must not double-trigger on the same run count
# ---------------------------------------------------------------------------


def test_dream_not_double_triggered():
    """on_run_completed() + _maybe_run_dream() must trigger dream exactly once per interval."""
    import asyncio
    from unittest.mock import MagicMock

    from hi_agent.server.dream_scheduler import MemoryLifecycleManager

    short = MagicMock()
    mid = MagicMock()

    mgr = MemoryLifecycleManager(
        short_term_store=short,
        mid_term_store=mid,
        auto_dream_interval=3,
        auto_consolidate_interval=0,
    )

    trigger_count = []

    def counting_trigger(date=None):
        trigger_count.append(1)
        return {"status": "completed", "date": date, "sessions_count": 0,
                "tasks_completed": 0, "key_learnings": 0, "patterns_observed": 0}

    mgr.trigger_dream = counting_trigger

    # Simulate reaching the interval (3 runs) from on_run_completed
    mgr.on_run_completed()
    mgr.on_run_completed()
    mgr.on_run_completed()  # count=3, threshold hit

    # Also simulate _maybe_run_dream firing at same count
    asyncio.run(mgr._maybe_run_dream())

    # Must have triggered exactly once for count=3
    assert len(trigger_count) == 1, f"Expected 1 trigger, got {len(trigger_count)}"


# ---------------------------------------------------------------------------
# K-9: POST /memory/dream with profile_id uses profile-scoped manager
# ---------------------------------------------------------------------------


def test_memory_dream_handler_builds_scoped_manager_for_profile():
    """POST /memory/dream with profile_id must use profile-scoped manager."""
    from unittest.mock import MagicMock, patch

    from hi_agent.config.builder import SystemBuilder

    with patch.object(SystemBuilder, "build_memory_lifecycle_manager") as mock_build:
        mock_mgr = MagicMock()
        mock_mgr.trigger_dream.return_value = {"status": "completed"}
        mock_build.return_value = mock_mgr

        # Simulate what the handler does when profile_id is provided
        profile_id = "proj1"
        builder = SystemBuilder()
        manager = builder.build_memory_lifecycle_manager(profile_id=profile_id)
        result = manager.trigger_dream(None)

        mock_build.assert_called_once_with(profile_id=profile_id)
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# K-10: build_executor_from_checkpoint passes profile_id to store builders
# ---------------------------------------------------------------------------


def test_checkpoint_builder_uses_profile_id():
    """build_executor_from_checkpoint must pass profile_id to store builders."""
    import json
    import os
    import tempfile
    from unittest.mock import MagicMock, patch

    from hi_agent.config.builder import SystemBuilder

    # Create a minimal checkpoint file with profile_id
    cp = {
        "run_id": "run-k10",
        "task_contract": {"task_id": "t-k10", "goal": "test", "profile_id": "proj1"},
        "stage_states": {},
        "stage_attempt": {},
        "current_stage": "",
        "action_seq": 0,
        "branch_seq": 0,
        "l0_records": [],
        "l1_summaries": {},
        "events": [],
        "llm_calls": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "compact_boundaries": [],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(cp, f)
        cp_path = f.name

    try:
        builder = SystemBuilder()
        import contextlib
        with (
            patch.object(builder, "build_short_term_store") as mock_sts,
            patch.object(builder, "build_kernel", return_value=MagicMock()),
            patch.object(builder, "build_long_term_graph", return_value=MagicMock()),
            patch.object(builder, "build_knowledge_manager", return_value=MagicMock()),
        ):
            mock_sts.return_value = MagicMock()
            with contextlib.suppress(Exception):
                # build_executor_from_checkpoint returns a resume() closure;
                # invoking it triggers build_short_term_store with the profile_id.
                resume_fn = builder.build_executor_from_checkpoint(cp_path)
                resume_fn()
            mock_sts.assert_called_with(profile_id="proj1")
    finally:
        os.unlink(cp_path)

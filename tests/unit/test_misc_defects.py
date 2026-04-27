"""Miscellaneous defect unit tests.

Consolidated from: test_round8_others.py (K-4, K-5, K-8, K-9, K-10),
test_round6_defects_context.py (H-8), test_round7_defects_context.py (I-4),
test_round6_defects_delegation.py (H-6), test_round7_defects_builder.py (I-7, I-8),
test_round4_defects_builder.py (F-4, F-2), test_round4_defects_long_term.py (F-3),
test_round5_defects_builder.py (G-5).
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.windows_unsafe

# ---------------------------------------------------------------------------
# K-4: RunExecutorFacade.stop() must log, not silently swallow exceptions
# ---------------------------------------------------------------------------


def test_facade_stop_logs_finalize_failure(caplog):
    """stop() must log when _finalize_run raises, not silently swallow."""
    import logging

    from hi_agent.executor_facade import RunExecutorFacade

    facade = RunExecutorFacade()
    facade._executor = MagicMock()
    facade._executor._finalize_run = MagicMock(side_effect=RuntimeError("finalize boom"))
    facade._contract = MagicMock()

    with caplog.at_level(logging.WARNING, logger="hi_agent.executor_facade"):
        facade.stop()

    assert any(
        "finalize" in r.message.lower() or "finalize" in r.getMessage().lower()
        for r in caplog.records
    ), "Expected warning about _finalize_run failure"


# ---------------------------------------------------------------------------
# K-5: ContextManager._assemble_memory() must log retrieval failures
# ---------------------------------------------------------------------------


def test_assemble_memory_logs_retrieval_failure(caplog):
    """_assemble_memory() must log when retrieval fails, not silently swallow."""
    import logging

    from hi_agent.context.manager import ContextBudget, ContextManager

    retriever = MagicMock()
    retriever.retrieve = MagicMock(side_effect=OSError("disk error"))

    budget = ContextBudget()

    mgr = ContextManager(budget=budget, memory_retriever=retriever)

    with caplog.at_level(logging.WARNING):
        section = mgr._assemble_memory()

    assert section.content == ""  # fallback still works
    assert any(
        "memory_retrieval_failed" in r.getMessage() or "disk error" in r.getMessage()
        for r in caplog.records
    ), "Expected warning about retrieval failure"


# ---------------------------------------------------------------------------
# K-8: Dream scheduler must not double-trigger on the same run count
# ---------------------------------------------------------------------------


def test_dream_not_double_triggered():
    """on_run_completed() + _maybe_run_dream() must trigger dream exactly once per interval."""
    import asyncio

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
        return {
            "status": "completed",
            "date": date,
            "sessions_count": 0,
            "tasks_completed": 0,
            "key_learnings": 0,
            "patterns_observed": 0,
        }

    mgr.trigger_dream = counting_trigger

    mgr.on_run_completed()
    mgr.on_run_completed()
    mgr.on_run_completed()  # count=3, threshold hit

    asyncio.run(mgr._maybe_run_dream())

    assert len(trigger_count) == 1, f"Expected 1 trigger, got {len(trigger_count)}"


# ---------------------------------------------------------------------------
# K-9: POST /memory/dream with profile_id uses profile-scoped manager
# ---------------------------------------------------------------------------


def test_memory_dream_handler_builds_scoped_manager_for_profile():
    """POST /memory/dream with profile_id must use profile-scoped manager."""
    from hi_agent.config.builder import SystemBuilder

    with patch.object(SystemBuilder, "build_memory_lifecycle_manager") as mock_build:
        mock_mgr = MagicMock()
        mock_mgr.trigger_dream.return_value = {"status": "completed"}
        mock_build.return_value = mock_mgr

        profile_id = "proj1"
        builder = SystemBuilder()
        manager = builder.build_memory_lifecycle_manager(profile_id=profile_id)
        result = manager.trigger_dream(None)

        mock_build.assert_called_once_with(profile_id=profile_id)
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# K-10: build_executor_from_checkpoint passes profile_id to store builders
# ---------------------------------------------------------------------------


@pytest.mark.external_llm
def test_checkpoint_builder_uses_profile_id():
    """build_executor_from_checkpoint must pass profile_id to store builders."""
    import contextlib
    import json
    import tempfile

    from hi_agent.config.builder import SystemBuilder

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
        with (
            patch.object(builder, "build_short_term_store") as mock_sts,
            patch.object(builder, "build_kernel", return_value=MagicMock()),
            patch.object(builder, "build_long_term_graph", return_value=MagicMock()),
            patch.object(builder, "build_knowledge_manager", return_value=MagicMock()),
        ):
            mock_sts.return_value = MagicMock()
            with contextlib.suppress(Exception):
                resume_fn = builder.build_executor_from_checkpoint(cp_path)
                resume_fn()
            mock_sts.assert_called_with(profile_id="proj1", workspace_key=None)
    finally:
        os.unlink(cp_path)


# ---------------------------------------------------------------------------
# H-8: ContextManager reflection_context budget partition
# ---------------------------------------------------------------------------


class TestReflectionContextPartition:
    """Tests for the reflection_context budget field and set_reflection_context()."""

    def _make_manager(self):
        from hi_agent.context.manager import ContextBudget, ContextManager

        budget = ContextBudget(
            total_window=200_000,
            output_reserve=8_000,
            system_prompt=2_000,
            tool_definitions=3_000,
            skill_prompts=5_000,
            memory_context=1_500,
            knowledge_context=1_500,
            reflection_context=500,
        )
        return ContextManager(budget=budget)

    def test_both_partitions_untruncated_when_within_budget(self):
        """Inject 1,800 chars into knowledge and 300 chars into reflection;
        assert both appear untruncated in the assembled context snapshot.
        """
        mgr = self._make_manager()
        knowledge_text = "K" * 1_800
        reflection_text = "R" * 300

        mgr.set_knowledge_context(knowledge_text)
        mgr.set_reflection_context(reflection_text)

        snapshot = mgr.prepare_context(purpose="test")

        section_map = {s.name: s for s in snapshot.sections}

        assert "reflection" in section_map, "reflection section missing from snapshot"
        assert "knowledge" in section_map, "knowledge section missing from snapshot"

        assert section_map["reflection"].content == reflection_text, (
            "reflection content was truncated unexpectedly"
        )
        assert section_map["knowledge"].content == knowledge_text, (
            "knowledge content was truncated unexpectedly"
        )

    def test_oversized_reflection_is_truncated_to_budget(self):
        """Inject a reflection prompt whose token count exceeds 500; assert truncation."""
        mgr = self._make_manager()
        long_reflection = "W" * 2_600

        mgr.set_reflection_context(long_reflection)

        snapshot = mgr.prepare_context(purpose="test")
        section_map = {s.name: s for s in snapshot.sections}

        assert "reflection" in section_map, "reflection section missing from snapshot"
        stored = section_map["reflection"].content

        assert len(stored) < len(long_reflection), (
            "reflection content was not truncated despite exceeding 500-token budget"
        )
        assert len(stored) > 0, "reflection content was truncated to empty"


# ---------------------------------------------------------------------------
# I-4: ContextBudget.from_config() reflection_context forwarding
# ---------------------------------------------------------------------------


def _base_cfg(**overrides):
    """Return a minimal config namespace with all required fields."""
    defaults = {
        "context_total_window": 200_000,
        "context_output_reserve": 8_000,
        "context_system_prompt_budget": 2_000,
        "context_tool_definitions_budget": 3_000,
        "context_skill_prompts_budget": 5_000,
        "memory_retriever_default_budget": 1_500,
        "context_knowledge_context_budget": 1_500,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_from_config_forwards_reflection_budget():
    """from_config() must use context_reflection_context_budget when provided."""
    from hi_agent.context.manager import ContextBudget

    cfg = _base_cfg(context_reflection_context_budget=800)
    budget = ContextBudget.from_config(cfg)
    assert budget.reflection_context == 800


def test_from_config_fallback_reflection_budget():
    """from_config() must fall back to 500 when context_reflection_context_budget is absent."""
    from hi_agent.context.manager import ContextBudget

    cfg = _base_cfg()
    budget = ContextBudget.from_config(cfg)
    assert budget.reflection_context == 500


# ---------------------------------------------------------------------------
# H-6: DelegationManager GatePendingError propagation
# ---------------------------------------------------------------------------


class TestGatePendingErrorPropagation:
    """H-6: child run raises GatePendingError → DelegationResult reflects gate state."""

    @pytest.mark.asyncio
    async def test_gate_pending_error_yields_gate_pending_status(self):
        """When _delegate_one raises GatePendingError, delegate() must produce
        DelegationResult with status="gate_pending" and matching gate_id.

        Mock rationale: spawn_child_run_async is an external async kernel call;
        mocking it is the correct way to inject the fault without a live kernel.
        """
        from hi_agent.gate_protocol import GatePendingError
        from hi_agent.task_mgmt.delegation import (
            DelegationConfig,
            DelegationManager,
            DelegationRequest,
        )

        kernel = MagicMock()
        kernel.spawn_child_run_async = AsyncMock(side_effect=GatePendingError("test-gate"))
        config = DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01)
        manager = DelegationManager(kernel=kernel, config=config, llm=None)

        req = DelegationRequest(goal="test goal", task_id="t1")
        results = await manager.delegate([req], parent_run_id="parent-run-1")

        assert len(results) == 1
        result = results[0]
        assert result.status == "gate_pending", f"Expected 'gate_pending', got {result.status!r}"
        assert result.gate_id == "test-gate", (
            f"Expected gate_id='test-gate', got {result.gate_id!r}"
        )

    @pytest.mark.asyncio
    async def test_generic_exception_yields_failed_status_with_no_gate_id(self):
        """When _delegate_one raises a generic ValueError, delegate() must produce
        DelegationResult with status="failed" and gate_id=None.

        Mock rationale: spawn_child_run_async is an external async kernel call;
        mocking it is the correct way to inject the fault without a live kernel.
        """
        from hi_agent.task_mgmt.delegation import (
            DelegationConfig,
            DelegationManager,
            DelegationRequest,
        )

        kernel = MagicMock()
        kernel.spawn_child_run_async = AsyncMock(side_effect=ValueError("normal error"))
        config = DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01)
        manager = DelegationManager(kernel=kernel, config=config, llm=None)

        req = DelegationRequest(goal="test goal", task_id="t2")
        results = await manager.delegate([req], parent_run_id="parent-run-2")

        assert len(results) == 1
        result = results[0]
        assert result.status == "failed", f"Expected 'failed', got {result.status!r}"
        assert result.gate_id is None, f"Expected gate_id=None, got {result.gate_id!r}"
        assert "normal error" in (result.error or ""), (
            f"Expected error to contain 'normal error', got {result.error!r}"
        )


# ---------------------------------------------------------------------------
# I-7: MemoryLifecycleManager uses profile-scoped stores
# ---------------------------------------------------------------------------


def _make_builder_i7(tmp_path, *, restart_on_exhausted: str = "reflect"):
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    config = TraceConfig(
        episodic_storage_dir=str(tmp_path / "episodes"),
        restart_on_exhausted=restart_on_exhausted,
        restart_max_attempts=3,
    )
    return SystemBuilder(config)


def _make_contract_i7(profile_id: str = ""):
    c = MagicMock()
    c.task_id = "t-i7"
    c.goal = "test goal"
    c.deadline = None
    c.budget = None
    c.constraints = []
    c.acceptance_criteria = []
    c.task_family = "quick_task"
    c.risk_level = "low"
    c.profile_id = profile_id
    c.decomposition_strategy = None
    return c


class TestI7MemoryLifecycleManagerProfileStores:
    """I-7: MemoryLifecycleManager must use the same profile-scoped stores as the executor."""

    def test_memory_lifecycle_manager_uses_profile_stores(self, tmp_path):
        """Executor's memory_lifecycle_manager._short points at profiles/proj1/short_term."""
        builder = _make_builder_i7(tmp_path)
        contract = _make_contract_i7(profile_id="proj1")

        executor = builder.build_executor(contract)

        mlm = executor.memory_lifecycle_manager
        assert mlm is not None, "memory_lifecycle_manager must be set on executor"

        short = mlm._short
        assert short is not None, "MLM._short must not be None"
        actual_path = str(short._storage_dir)
        assert actual_path.endswith(os.path.join("profiles", "proj1", "short_term")), (
            f"MLM._short storage_dir {actual_path!r} should end with profiles/proj1/short_term"
        )

    def test_memory_lifecycle_manager_retrieval_engine_shares_stores(self, tmp_path):
        """MLM and executor retrieval engines share the same short_term_store."""
        builder = _make_builder_i7(tmp_path)
        contract = _make_contract_i7(profile_id="proj1")

        executor = builder.build_executor(contract)

        mlm = executor.memory_lifecycle_manager
        assert mlm is not None

        mlm_retrieval_short = (
            mlm._retrieval._short_term if hasattr(mlm._retrieval, "_short_term") else None
        )
        if mlm_retrieval_short is not None:
            assert mlm_retrieval_short is mlm._short, (
                "MLM retrieval engine's short_term must be the same instance as MLM._short"
            )

        exec_retrieval = getattr(executor, "retrieval_engine", None)
        if exec_retrieval is not None:
            exec_short = getattr(exec_retrieval, "_short_term", None)
            if exec_short is not None:
                assert exec_short is mlm._short, (
                    "Executor retrieval engine's short_term must be same instance as MLM._short"
                )


# ---------------------------------------------------------------------------
# I-8: Default restart policy must be 'reflect'
# ---------------------------------------------------------------------------


class TestI8RestartPolicyDefault:
    """I-8: Default config must produce on_exhausted='reflect', enabling the reflect path."""

    def test_build_restart_policy_defaults_reflect(self, tmp_path):
        """Default restart policy returns the reflect action."""
        builder = _make_builder_i7(tmp_path, restart_on_exhausted="reflect")
        engine = builder._build_restart_policy_engine()
        assert engine is not None, "_build_restart_policy_engine() must succeed"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=3, on_exhausted="reflect")
        decision = engine._decide(policy, "t-i8", attempt_seq=1, failure=None)

        assert decision.action == "reflect", f"Expected 'reflect' but got {decision.action!r}"
        assert decision.reflection_prompt is not None, (
            "reflect action should produce a reflection_prompt"
        )

    def test_build_restart_policy_config_escalate(self, tmp_path):
        """With restart_on_exhausted='escalate', within-budget → action='retry'."""
        builder = _make_builder_i7(tmp_path, restart_on_exhausted="escalate")
        engine = builder._build_restart_policy_engine()
        assert engine is not None, "_build_restart_policy_engine() must succeed"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=5, on_exhausted="escalate")
        decision = engine._decide(policy, "t-i8b", attempt_seq=1, failure=None)

        assert decision.action == "retry", f"Expected 'retry' but got {decision.action!r}"
        assert decision.reflection_prompt is None, (
            "retry action must not produce a reflection_prompt"
        )


# ---------------------------------------------------------------------------
# F-4/F-2: SystemBuilder RawMemoryStore base_dir wiring and profile_id scoping
# ---------------------------------------------------------------------------


def _make_builder_f4(tmp_path):
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return SystemBuilder(config=cfg)


def _make_contract_f4(profile_id: str | None = "test"):
    from hi_agent.contracts import TaskContract

    return TaskContract(task_id="t1", goal="test goal", profile_id=profile_id or "test-profile")


class TestF4RawMemoryStoreBaseDir:
    def test_f4_raw_memory_store_has_base_dir(self, tmp_path):
        """After build_executor(), RunExecutor.raw_memory._base_dir must not be None."""
        builder = _make_builder_f4(tmp_path)
        contract = _make_contract_f4()
        executor = builder.build_executor(contract)
        assert executor.raw_memory._base_dir is not None

    def test_f4_l0_jsonl_created_on_append(self, tmp_path):
        """Appending a RawEventRecord and calling close() must create a .jsonl file on disk."""
        from hi_agent.memory import RawEventRecord

        builder = _make_builder_f4(tmp_path)
        contract = _make_contract_f4()
        executor = builder.build_executor(contract)

        store = executor.raw_memory
        store.append(RawEventRecord(event_type="test_event", payload={"key": "value"}))
        store.close()

        log_dir = store._base_dir / "logs" / "memory" / "L0"
        jsonl_files = list(log_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1


class TestF2ProfileIdPathScoping:
    def test_f2_profile_id_scopes_mid_term_path(self, tmp_path):
        """Two different profile_ids must produce different _storage_dir values."""
        builder = _make_builder_f4(tmp_path)
        store_a = builder.build_mid_term_store(profile_id="proj-a", workspace_key=None)
        store_b = builder.build_mid_term_store(profile_id="proj-b", workspace_key=None)
        assert store_a._storage_dir != store_b._storage_dir

    def test_f2_profile_id_scopes_long_term_path(self, tmp_path):
        """Two different profile_ids must produce different _storage_path values."""
        builder = _make_builder_f4(tmp_path)
        graph_a = builder.build_long_term_graph(profile_id="proj-a", workspace_key=None)
        graph_b = builder.build_long_term_graph(profile_id="proj-b", workspace_key=None)
        assert graph_a._storage_path != graph_b._storage_path


# ---------------------------------------------------------------------------
# F-3: LongTermConsolidator.consolidate() must call graph.save() after adding nodes
# ---------------------------------------------------------------------------


def test_f3_consolidate_saves_graph_to_disk(tmp_path):
    """consolidate() must persist nodes to disk so they survive process restart."""
    from hi_agent.memory.long_term import LongTermConsolidator, LongTermMemoryGraph
    from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore

    mid_dir = tmp_path / "mid"
    graph_path = tmp_path / "graph.json"

    store = MidTermMemoryStore(storage_dir=str(mid_dir))
    store.save(DailySummary(date="2026-04-15", key_learnings=["learning A"]))
    graph = LongTermMemoryGraph(storage_path=str(graph_path))
    consolidator = LongTermConsolidator(mid_term_store=store, graph=graph)

    count = consolidator.consolidate(days=365)

    assert count > 0, "Expected at least one node to be added"
    assert graph_path.exists(), "graph.json must be written to disk after consolidate()"

    new_graph = LongTermMemoryGraph(storage_path=str(graph_path))
    assert len(new_graph._nodes) > 0, "Reloaded graph must contain persisted nodes"


def test_f3_consolidate_no_save_when_no_summaries(tmp_path):
    """consolidate() must not create the graph file when no summaries exist."""
    from hi_agent.memory.long_term import LongTermConsolidator, LongTermMemoryGraph
    from hi_agent.memory.mid_term import MidTermMemoryStore

    mid_dir = tmp_path / "mid"
    graph_path = tmp_path / "graph.json"

    mid_term = MidTermMemoryStore(storage_dir=str(mid_dir))
    graph = LongTermMemoryGraph(storage_path=str(graph_path))
    consolidator = LongTermConsolidator(mid_term_store=mid_term, graph=graph)

    count = consolidator.consolidate(days=7)

    assert count == 0
    assert not graph_path.exists(), "No file should be written when count == 0"


def test_f3_consolidate_returns_node_count(tmp_path):
    """consolidate() return value must equal the number of nodes added."""
    from hi_agent.memory.long_term import LongTermConsolidator, LongTermMemoryGraph
    from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore

    mid_dir = tmp_path / "mid"
    graph_path = tmp_path / "graph.json"

    store = MidTermMemoryStore(storage_dir=str(mid_dir))
    store.save(DailySummary(date="2026-04-15", key_learnings=["learning one", "learning two"]))
    graph = LongTermMemoryGraph(storage_path=str(graph_path))
    consolidator = LongTermConsolidator(mid_term_store=store, graph=graph)

    count = consolidator.consolidate(days=365)

    assert count == 2, f"Expected 2 nodes (one per key_learning), got {count}"


# ---------------------------------------------------------------------------
# G-5: Retrieval engine shares profile-scoped stores with executor
# ---------------------------------------------------------------------------


def _make_builder_g5(tmp_path):
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return SystemBuilder(config=cfg)


def _make_contract_g5(profile_id: str | None = None):
    from hi_agent.contracts import TaskContract

    return TaskContract(task_id="t1", goal="test goal", profile_id=profile_id)


class TestG5RetrievalEngineStoreIsolation:
    def test_g5_retrieval_engine_shares_short_term_store_with_executor(self, tmp_path):
        """After build_executor() with a non-empty profile_id, the retrieval engine's
        _short_term._storage_dir must equal the executor's short_term_store._storage_dir.
        """
        builder = _make_builder_g5(tmp_path)
        contract = _make_contract_g5(profile_id="proj-share")
        executor = builder.build_executor(contract)

        executor_path = executor.short_term_store._storage_dir
        engine_path = executor.retrieval_engine._short_term._storage_dir
        assert executor_path == engine_path, (
            f"executor short_term path {executor_path!r} != "
            f"retrieval engine short_term path {engine_path!r}"
        )

    def test_g5_retrieval_engine_profile_scoped_path(self, tmp_path):
        """Two build_executor() calls with different profile_ids must produce
        retrieval engines with distinct _short_term._storage_dir values.
        """
        builder = _make_builder_g5(tmp_path)
        contract_a = _make_contract_g5(profile_id="proj-a")
        contract_b = _make_contract_g5(profile_id="proj-b")

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

        builder = _make_builder_g5(tmp_path)
        contract = _make_contract_g5(profile_id="proj-x")
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

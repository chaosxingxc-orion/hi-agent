"""Integration tests for policy version pinning, episodic memory in task view,
and knowledge store enhancements."""

from __future__ import annotations

import pytest
from dataclasses import asdict

from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.knowledge.entry import KnowledgeEntry
from hi_agent.knowledge.store import InMemoryKnowledgeStore
from hi_agent.memory.episodic import EpisodeRecord, EpisodicMemoryStore
from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.l2_index import RunMemoryIndex
from hi_agent.memory.retriever import MemoryRetriever
from hi_agent.task_view.builder import TaskView, build_task_view
from hi_agent.task_view.token_budget import DEFAULT_BUDGET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(
    run_id: str = "run-1", stages: list[tuple[str, str]] | None = None
) -> RunMemoryIndex:
    idx = RunMemoryIndex(run_id=run_id)
    for sid, outcome in (stages or []):
        idx.add_stage(sid, outcome)
    return idx


def _make_stage(
    stage_id: str = "S1",
    findings: list[str] | None = None,
    decisions: list[str] | None = None,
    outcome: str = "active",
) -> CompressedStageMemory:
    return CompressedStageMemory(
        stage_id=stage_id,
        findings=findings or [f"finding-{stage_id}"],
        decisions=decisions or [f"decision-{stage_id}"],
        outcome=outcome,
        key_entities=["entity-a"],
        source_evidence_count=5,
    )


def _make_episode(
    run_id: str,
    task_family: str = "test_family",
    outcome: str = "completed",
    goal: str = "test goal",
    failure_codes: list[str] | None = None,
) -> EpisodeRecord:
    return EpisodeRecord(
        run_id=run_id,
        task_id=f"task-{run_id}",
        task_family=task_family,
        goal=goal,
        outcome=outcome,
        stages_completed=["S1", "S2"],
        key_findings=["found-something"],
        key_decisions=["decided-something"],
        failure_codes=failure_codes or [],
        timestamp="2026-01-01T00:00:00",
    )


# ---------------------------------------------------------------------------
# 1. PolicyVersionSet tests
# ---------------------------------------------------------------------------


class TestPolicyVersionSetFrozen:
    """Policy versions must be frozen at run start."""

    def test_default_construction(self) -> None:
        pvs = PolicyVersionSet()
        assert pvs.route_policy == "route_v1"
        assert pvs.acceptance_policy == "acceptance_v1"
        assert pvs.skill_policy == "skill_v1"

    def test_frozen_immutable(self) -> None:
        pvs = PolicyVersionSet()
        with pytest.raises(AttributeError):
            pvs.route_policy = "route_v2"  # type: ignore[misc]

    def test_custom_versions(self) -> None:
        pvs = PolicyVersionSet(
            route_policy="route_v2",
            evaluation_policy="eval_v3",
        )
        assert pvs.route_policy == "route_v2"
        assert pvs.evaluation_policy == "eval_v3"
        # Other fields keep defaults
        assert pvs.acceptance_policy == "acceptance_v1"

    def test_policy_versions_in_runner_init(self) -> None:
        """RunExecutor stores policy_versions and it is frozen."""
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor
        from hi_agent.runtime_adapter.mock_kernel import MockKernel

        contract = TaskContract(
            task_id="t1",
            goal="test",
            task_family="quick_task",
        )
        custom_pvs = PolicyVersionSet(route_policy="route_v99")
        executor = RunExecutor(
            contract, MockKernel(strict_mode=True), policy_versions=custom_pvs
        )
        assert executor.policy_versions is custom_pvs
        assert executor.policy_versions.route_policy == "route_v99"
        # Frozen
        with pytest.raises(AttributeError):
            executor.policy_versions.route_policy = "changed"  # type: ignore[misc]

    def test_policy_versions_default_in_runner(self) -> None:
        """RunExecutor defaults to PolicyVersionSet() when none provided."""
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor
        from hi_agent.runtime_adapter.mock_kernel import MockKernel

        contract = TaskContract(
            task_id="t2",
            goal="test",
            task_family="quick_task",
        )
        executor = RunExecutor(contract, MockKernel(strict_mode=True))
        assert isinstance(executor.policy_versions, PolicyVersionSet)
        assert executor.policy_versions.route_policy == "route_v1"


# ---------------------------------------------------------------------------
# 2. Policy versions in task_view payloads (tested via postmortem)
# ---------------------------------------------------------------------------


class TestPolicyVersionsInPostmortem:
    def test_postmortem_includes_policy_versions(self) -> None:
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor
        from hi_agent.runtime_adapter.mock_kernel import MockKernel

        pvs = PolicyVersionSet(route_policy="route_v5", skill_policy="skill_v3")
        contract = TaskContract(
            task_id="t-pm",
            goal="postmortem test",
            task_family="quick_task",
        )
        executor = RunExecutor(
            contract, MockKernel(strict_mode=True), policy_versions=pvs
        )
        postmortem = executor._build_postmortem("completed")
        assert postmortem.policy_versions["route_policy"] == "route_v5"
        assert postmortem.policy_versions["skill_policy"] == "skill_v3"
        assert postmortem.policy_versions["acceptance_policy"] == "acceptance_v1"


# ---------------------------------------------------------------------------
# 3. Episodic memory retriever integrated into task view builder
# ---------------------------------------------------------------------------


class TestEpisodicMemoryInTaskView:
    def test_retriever_adds_episodic_layer(self, tmp_path) -> None:
        """When a memory_retriever is provided, an 'episodic' layer appears."""
        store = EpisodicMemoryStore(storage_dir=str(tmp_path / "episodes"))
        store.store(_make_episode("run-old-1", task_family="qa"))
        store.store(_make_episode("run-old-2", task_family="qa"))

        retriever = MemoryRetriever(episodic_store=store)

        view = build_task_view(
            run_index=_make_index("run-new", [("S1", "active")]),
            current_stage_summary=_make_stage("S1"),
            memory_retriever=retriever,
            task_family="qa",
            stage_id="S1",
        )

        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "episodic" in layers

    def test_no_retriever_no_episodic_layer(self) -> None:
        """Without a retriever, no episodic layer."""
        view = build_task_view(
            run_index=_make_index("run-x", [("S1", "active")]),
            current_stage_summary=_make_stage("S1"),
        )
        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "episodic" not in layers

    def test_retriever_with_no_episodes_no_layer(self) -> None:
        """Retriever present but empty store produces no episodic layer."""
        store = EpisodicMemoryStore(storage_dir="/nonexistent/path")
        retriever = MemoryRetriever(episodic_store=store)

        view = build_task_view(
            run_index=_make_index("run-y"),
            memory_retriever=retriever,
            task_family="unknown",
            stage_id="S1",
        )
        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "episodic" not in layers


# ---------------------------------------------------------------------------
# 4. Episodic snippets respect token budget
# ---------------------------------------------------------------------------


class TestEpisodicBudget:
    def test_episodic_respects_tight_budget(self, tmp_path) -> None:
        """With a very tight budget, episodic layer gets dropped."""
        store = EpisodicMemoryStore(storage_dir=str(tmp_path / "ep"))
        store.store(_make_episode("r1", task_family="fam"))

        retriever = MemoryRetriever(episodic_store=store)

        # Budget so tight that system_reserved eats everything
        view = build_task_view(
            run_index=_make_index("run-tight", [("S1", "ok")]),
            current_stage_summary=_make_stage("S1"),
            memory_retriever=retriever,
            task_family="fam",
            stage_id="S1",
            budget=515,  # just above system_reserved=512
        )
        assert isinstance(view, TaskView)
        assert view.total_tokens <= 515

    def test_episodic_coexists_with_other_layers(self, tmp_path) -> None:
        """Episodic layer coexists with l2, l1, knowledge."""
        store = EpisodicMemoryStore(storage_dir=str(tmp_path / "ep2"))
        store.store(_make_episode("r-past", task_family="mix"))

        retriever = MemoryRetriever(episodic_store=store)

        view = build_task_view(
            run_index=_make_index("run-mix", [("S1", "done"), ("S2", "active")]),
            current_stage_summary=_make_stage("S2"),
            previous_stage_summary=_make_stage("S1", outcome="done"),
            episodes=[{"ev": "inline"}],
            knowledge_records=["fact-1"],
            memory_retriever=retriever,
            task_family="mix",
            stage_id="S2",
        )
        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "l2_index" in layers
        assert "l1_current_stage" in layers
        assert "episodic" in layers


# ---------------------------------------------------------------------------
# 5. Knowledge store: batch upsert and tag search
# ---------------------------------------------------------------------------


class TestKnowledgeStoreBatch:
    def test_upsert_batch_basic(self) -> None:
        store = InMemoryKnowledgeStore()
        entries = [
            KnowledgeEntry(entry_id="e1", content="Python is dynamic", tags=["lang"]),
            KnowledgeEntry(entry_id="e2", content="Rust is safe", tags=["lang", "systems"]),
            KnowledgeEntry(entry_id="e3", content="Go is fast", tags=["lang"]),
        ]
        count = store.upsert_batch(entries)
        assert count == 3
        assert len(store.all_records()) == 3

    def test_upsert_batch_skips_empty(self) -> None:
        store = InMemoryKnowledgeStore()
        entries = [
            KnowledgeEntry(entry_id="", content="no id"),
            KnowledgeEntry(entry_id="e1", content=""),
            KnowledgeEntry(entry_id="e2", content="valid", source="src"),
        ]
        count = store.upsert_batch(entries)
        assert count == 1

    def test_upsert_batch_overwrites(self) -> None:
        store = InMemoryKnowledgeStore()
        store.upsert_batch([
            KnowledgeEntry(entry_id="e1", content="old", source="s"),
        ])
        store.upsert_batch([
            KnowledgeEntry(entry_id="e1", content="new", source="s"),
        ])
        rec = store.get(source="s", key="e1")
        assert rec is not None
        assert rec.content == "new"

    def test_upsert_batch_empty_list(self) -> None:
        store = InMemoryKnowledgeStore()
        assert store.upsert_batch([]) == 0


class TestKnowledgeStoreTagSearch:
    def test_search_by_single_tag(self) -> None:
        store = InMemoryKnowledgeStore()
        store.upsert_batch([
            KnowledgeEntry(entry_id="e1", content="A", tags=["alpha"]),
            KnowledgeEntry(entry_id="e2", content="B", tags=["beta"]),
            KnowledgeEntry(entry_id="e3", content="C", tags=["alpha", "beta"]),
        ])
        results = store.search_by_tags(["alpha"])
        assert len(results) == 2
        ids = {r.entry_id for r in results}
        assert ids == {"e1", "e3"}

    def test_search_by_multiple_tags(self) -> None:
        store = InMemoryKnowledgeStore()
        store.upsert_batch([
            KnowledgeEntry(entry_id="e1", content="A", tags=["x", "y"]),
            KnowledgeEntry(entry_id="e2", content="B", tags=["x"]),
            KnowledgeEntry(entry_id="e3", content="C", tags=["x", "y", "z"]),
        ])
        results = store.search_by_tags(["x", "y"])
        assert len(results) == 2
        ids = {r.entry_id for r in results}
        assert ids == {"e1", "e3"}

    def test_search_by_tags_empty(self) -> None:
        store = InMemoryKnowledgeStore()
        assert store.search_by_tags([]) == []

    def test_search_by_tags_respects_limit(self) -> None:
        store = InMemoryKnowledgeStore()
        store.upsert_batch([
            KnowledgeEntry(entry_id=f"e{i}", content=f"fact {i}", tags=["common"])
            for i in range(20)
        ])
        results = store.search_by_tags(["common"], limit=5)
        assert len(results) == 5


class TestKnowledgeStoreStats:
    def test_get_stats_empty(self) -> None:
        store = InMemoryKnowledgeStore()
        stats = store.get_stats()
        assert stats["total"] == 0
        assert stats["by_source"] == {}
        assert stats["tag_distribution"] == {}

    def test_get_stats_populated(self) -> None:
        store = InMemoryKnowledgeStore()
        store.upsert_batch([
            KnowledgeEntry(entry_id="e1", content="A", tags=["t1", "t2"], source="s1"),
            KnowledgeEntry(entry_id="e2", content="B", tags=["t1"], source="s1"),
            KnowledgeEntry(entry_id="e3", content="C", tags=["t2"], source="s2"),
        ])
        stats = store.get_stats()
        assert stats["total"] == 3
        assert stats["by_source"]["s1"] == 2
        assert stats["by_source"]["s2"] == 1
        assert stats["tag_distribution"]["t1"] == 2
        assert stats["tag_distribution"]["t2"] == 2


# ---------------------------------------------------------------------------
# 6. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_build_task_view_without_new_params(self) -> None:
        """All new parameters are optional -- old call-sites still work."""
        view = build_task_view(
            run_index=_make_index("r", [("S1", "ok")]),
            current_stage_summary=_make_stage("S1"),
        )
        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "episodic" not in layers

    def test_runner_without_policy_versions(self) -> None:
        from hi_agent.contracts import TaskContract
        from hi_agent.runner import RunExecutor
        from hi_agent.runtime_adapter.mock_kernel import MockKernel

        contract = TaskContract(
            task_id="t-compat",
            goal="backward compat",
            task_family="quick_task",
        )
        executor = RunExecutor(contract, MockKernel(strict_mode=True))
        # Should get default PolicyVersionSet
        assert executor.policy_versions.route_policy == "route_v1"

    def test_knowledge_store_old_methods_still_work(self) -> None:
        store = InMemoryKnowledgeStore()
        rec = store.upsert(source="s", key="k", content="hello", tags=["t"])
        assert rec.content == "hello"
        found = store.search(query="hello", top_k=1)
        assert len(found) == 1

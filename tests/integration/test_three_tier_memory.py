"""Tests for the three-tier memory system (short/mid/long-term)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from hi_agent.memory.long_term import (
    LongTermConsolidator,
    LongTermMemoryGraph,
    MemoryEdge,
    MemoryNode,
)
from hi_agent.memory.mid_term import (
    DailySummary,
    DreamConsolidator,
    MidTermMemoryStore,
)
from hi_agent.memory.short_term import ShortTermMemory, ShortTermMemoryStore
from hi_agent.memory.unified_retriever import MemoryContext, UnifiedMemoryRetriever

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeTaskContract:
    goal: str = "Analyze code quality"


class _FakeRunSession:
    """Minimal mock of RunSession for build_from_session."""

    def __init__(
        self,
        run_id: str = "run-001",
        goal: str = "Analyze code quality",
        stage_states: dict[str, str] | None = None,
        l1_summaries: dict[str, dict] | None = None,
        l0_records: list[dict] | None = None,
        total_input_tokens: int = 100,
        total_output_tokens: int = 200,
        total_cost_usd: float = 0.05,
    ) -> None:
        self.run_id = run_id
        self.task_contract = _FakeTaskContract(goal=goal)
        self.stage_states = stage_states or {"S1": "completed", "S2": "completed"}
        self.l1_summaries = l1_summaries or {
            "S1": {"findings": ["found issue A", "found issue B"], "decisions": ["chose path X"]},
            "S2": {"findings": ["found issue A"], "decisions": ["chose path Y"]},
        }
        self.l0_records = l0_records or [
            {"event_type": "tool_call", "payload": {"tool": "grep"}},
            {"event_type": "tool_call", "payload": {"tool": "grep"}},
            {"event_type": "tool_call", "payload": {"tool": "read_file"}},
            {"event_type": "action_executed", "payload": {"tool": "write_file"}},
            {"event_type": "error", "payload": {"failure_code": "missing_evidence"}},
        ]
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.total_cost_usd = total_cost_usd


@pytest.fixture()
def st_store(tmp_path: Any) -> ShortTermMemoryStore:
    return ShortTermMemoryStore(storage_dir=str(tmp_path / "short_term"))


@pytest.fixture()
def mt_store(tmp_path: Any) -> MidTermMemoryStore:
    return MidTermMemoryStore(storage_dir=str(tmp_path / "mid_term"))


@pytest.fixture()
def lt_graph(tmp_path: Any) -> LongTermMemoryGraph:
    return LongTermMemoryGraph(storage_path=str(tmp_path / "long_term" / "graph.json"))


# ===========================================================================
# Short-Term Memory
# ===========================================================================


class TestShortTermMemory:
    def test_build_from_session(self, st_store: ShortTermMemoryStore) -> None:
        session = _FakeRunSession()
        mem = st_store.build_from_session(session)

        assert mem.run_id == "run-001"
        assert mem.task_goal == "Analyze code quality"
        assert "S1" in mem.stages_completed
        assert "S2" in mem.stages_completed
        # Deduplication: "found issue A" appears in both stages
        assert mem.key_findings.count("found issue A") == 1
        assert "found issue B" in mem.key_findings
        assert sorted(mem.tools_used) == ["grep", "read_file", "write_file"]
        assert "missing_evidence" in mem.errors_encountered
        assert mem.outcome == "completed"
        assert mem.total_tokens_used == 300

    def test_save_load_roundtrip(self, st_store: ShortTermMemoryStore) -> None:
        mem = ShortTermMemory(
            session_id="sess-001",
            run_id="run-001",
            task_goal="test goal",
            stages_completed=["S1"],
            key_findings=["finding A"],
            key_decisions=["decision B"],
            tools_used=["grep"],
            errors_encountered=["missing_evidence"],
            outcome="completed",
            duration_seconds=10.5,
            total_tokens_used=500,
            total_cost_usd=0.02,
        )
        st_store.save(mem)
        loaded = st_store.load("sess-001")

        assert loaded is not None
        assert loaded.session_id == "sess-001"
        assert loaded.task_goal == "test goal"
        assert loaded.key_findings == ["finding A"]
        assert loaded.total_tokens_used == 500
        assert loaded.created_at != ""  # auto-populated

    def test_list_recent_ordering(self, st_store: ShortTermMemoryStore) -> None:
        for i in range(5):
            mem = ShortTermMemory(
                session_id=f"sess-{i:03d}",
                run_id=f"run-{i:03d}",
                task_goal=f"goal {i}",
                created_at=f"2026-04-07T{10 + i:02d}:00:00+00:00",
            )
            st_store.save(mem)

        recent = st_store.list_recent(limit=3)
        assert len(recent) == 3
        # Newest first
        assert recent[0].session_id == "sess-004"
        assert recent[1].session_id == "sess-003"
        assert recent[2].session_id == "sess-002"

    def test_to_context_string_respects_max_tokens(self) -> None:
        mem = ShortTermMemory(
            session_id="sess-001",
            run_id="run-001",
            task_goal="A" * 2000,
            key_findings=["B" * 500],
        )
        text = mem.to_context_string(max_tokens=100)
        # 100 tokens ~ 400 chars
        assert len(text) <= 403  # 400 + "..."

    def test_load_nonexistent(self, st_store: ShortTermMemoryStore) -> None:
        assert st_store.load("nonexistent") is None

    def test_build_from_session_failed(self, st_store: ShortTermMemoryStore) -> None:
        session = _FakeRunSession(
            stage_states={"S1": "completed", "S2": "failed"},
        )
        mem = st_store.build_from_session(session)
        assert mem.outcome == "failed"


# ===========================================================================
# Mid-Term Memory
# ===========================================================================


class TestMidTermMemory:
    def test_save_load_roundtrip(self, mt_store: MidTermMemoryStore) -> None:
        summary = DailySummary(
            date="2026-04-07",
            sessions_count=3,
            tasks_completed=["task A"],
            tasks_failed=["task B"],
            key_learnings=["learned X"],
            patterns_observed=["pattern Y"],
            skills_used=["grep", "read_file"],
            total_tokens=1000,
            total_cost_usd=0.10,
        )
        mt_store.save(summary)
        loaded = mt_store.load("2026-04-07")

        assert loaded is not None
        assert loaded.date == "2026-04-07"
        assert loaded.sessions_count == 3
        assert loaded.tasks_completed == ["task A"]
        assert loaded.key_learnings == ["learned X"]
        assert loaded.created_at != ""

    def test_list_recent(self, mt_store: MidTermMemoryStore) -> None:
        for day in range(1, 6):
            mt_store.save(
                DailySummary(
                    date=f"2026-04-{day:02d}",
                    sessions_count=day,
                    created_at=f"2026-04-{day:02d}T23:59:00+00:00",
                )
            )
        recent = mt_store.list_recent(days=3)
        assert len(recent) == 3
        assert recent[0].date == "2026-04-05"
        assert recent[2].date == "2026-04-03"

    def test_load_nonexistent(self, mt_store: MidTermMemoryStore) -> None:
        assert mt_store.load("2099-01-01") is None

    def test_to_context_string(self) -> None:
        summary = DailySummary(
            date="2026-04-07",
            sessions_count=2,
            tasks_completed=["built feature"],
            key_learnings=["use caching"],
        )
        text = summary.to_context_string(max_tokens=300)
        assert "2026-04-07" in text
        assert "built feature" in text
        assert "use caching" in text


class TestDreamConsolidator:
    def test_consolidate_multiple_sessions(
        self, st_store: ShortTermMemoryStore, mt_store: MidTermMemoryStore
    ) -> None:
        # Create short-term memories for the same date
        for i in range(3):
            mem = ShortTermMemory(
                session_id=f"sess-{i}",
                run_id=f"run-{i}",
                task_goal=f"task {i}",
                key_findings=[f"finding {i}", "common finding"],
                key_decisions=[f"decision {i}"],
                tools_used=["grep", f"tool_{i}"],
                errors_encountered=["missing_evidence"] if i == 0 else [],
                outcome="completed" if i != 2 else "failed",
                total_tokens_used=100 * (i + 1),
                total_cost_usd=0.01 * (i + 1),
                created_at=f"2026-04-07T{10 + i:02d}:00:00+00:00",
            )
            st_store.save(mem)

        consolidator = DreamConsolidator(st_store, mt_store)
        summary = consolidator.consolidate(date="2026-04-07")

        assert summary.date == "2026-04-07"
        assert summary.sessions_count == 3
        assert len(summary.tasks_completed) == 2  # sessions 0 and 1
        assert len(summary.tasks_failed) == 1  # session 2
        assert summary.total_tokens == 600  # 100 + 200 + 300
        # Skills (tools) merged across sessions
        assert "grep" in summary.skills_used

    def test_deduplicate_findings(
        self, st_store: ShortTermMemoryStore, mt_store: MidTermMemoryStore
    ) -> None:
        consolidator = DreamConsolidator(st_store, mt_store)
        findings = [
            "found issue A",
            "found issue A",
            "found issue A in module X",  # near-dup (contains "found issue a")
            "unique finding",
        ]
        result = consolidator._deduplicate_findings(findings)
        # "found issue A" exact dup removed; "found issue A in module X" subsumes it
        assert "unique finding" in result
        # The longer version should survive
        assert any("module X" in f for f in result)
        # No exact duplicates
        assert len(result) == len({r.strip().lower() for r in result})

    def test_extract_patterns(
        self, st_store: ShortTermMemoryStore, mt_store: MidTermMemoryStore
    ) -> None:
        consolidator = DreamConsolidator(st_store, mt_store)
        sessions = [
            ShortTermMemory(
                session_id="s1",
                run_id="r1",
                task_goal="g1",
                tools_used=["grep", "read_file"],
                errors_encountered=["missing_evidence"],
                stages_completed=["S1", "S2"],
            ),
            ShortTermMemory(
                session_id="s2",
                run_id="r2",
                task_goal="g2",
                tools_used=["grep", "write_file"],
                errors_encountered=["missing_evidence"],
                stages_completed=["S1"],
            ),
        ]
        patterns = consolidator._extract_patterns(sessions)
        # grep used in 2/2, missing_evidence in 2/2, S1 in 2/2
        assert any("grep" in p for p in patterns)
        assert any("missing_evidence" in p for p in patterns)
        assert any("S1" in p for p in patterns)

    def test_extract_patterns_single_session(
        self, st_store: ShortTermMemoryStore, mt_store: MidTermMemoryStore
    ) -> None:
        consolidator = DreamConsolidator(st_store, mt_store)
        sessions = [
            ShortTermMemory(session_id="s1", run_id="r1", task_goal="g1"),
        ]
        assert consolidator._extract_patterns(sessions) == []


# ===========================================================================
# Long-Term Memory
# ===========================================================================


class TestLongTermMemoryGraph:
    def test_add_and_get_node(self, lt_graph: LongTermMemoryGraph) -> None:
        node = MemoryNode(node_id="n1", content="Python uses GIL", tags=["python"])
        lt_graph.add_node(node)
        retrieved = lt_graph.get_node("n1")
        assert retrieved is not None
        assert retrieved.content == "Python uses GIL"
        assert retrieved.created_at != ""

    def test_update_node(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="old"))
        lt_graph.update_node("n1", content="new", tags=["updated"])
        node = lt_graph.get_node("n1")
        assert node is not None
        assert node.content == "new"
        assert node.tags == ["updated"]

    def test_remove_node(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a"))
        lt_graph.add_node(MemoryNode(node_id="n2", content="b"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="supports"))
        lt_graph.remove_node("n1")
        assert lt_graph.get_node("n1") is None
        assert lt_graph.edge_count() == 0
        assert lt_graph.node_count() == 1

    def test_add_remove_edge(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a"))
        lt_graph.add_node(MemoryNode(node_id="n2", content="b"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="supports"))
        assert lt_graph.edge_count() == 1
        lt_graph.remove_edge("n1", "n2")
        assert lt_graph.edge_count() == 0

    def test_add_edge_missing_node(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n99", relation_type="x"))
        assert lt_graph.edge_count() == 0  # should not add

    def test_search_by_keyword(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="Python uses GIL for threading"))
        lt_graph.add_node(MemoryNode(node_id="n2", content="Rust has no GIL"))
        lt_graph.add_node(MemoryNode(node_id="n3", content="Java has JVM"))
        results = lt_graph.search("GIL threading")
        assert len(results) >= 1
        assert results[0].node_id == "n1"  # has both keywords

    def test_search_by_tags(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a", tags=["python", "concurrency"]))
        lt_graph.add_node(MemoryNode(node_id="n2", content="b", tags=["rust"]))
        results = lt_graph.search_by_tags(["python"])
        assert len(results) == 1
        assert results[0].node_id == "n1"

    def test_search_by_type(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a", node_type="fact"))
        lt_graph.add_node(MemoryNode(node_id="n2", content="b", node_type="pattern"))
        results = lt_graph.search_by_type("pattern")
        assert len(results) == 1
        assert results[0].node_id == "n2"

    def test_get_neighbors(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="center"))
        lt_graph.add_node(MemoryNode(node_id="n2", content="supports"))
        lt_graph.add_node(MemoryNode(node_id="n3", content="contradicts"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="supports"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n3", relation_type="contradicts"))

        all_neighbors = lt_graph.get_neighbors("n1")
        assert len(all_neighbors) == 2

        supports_only = lt_graph.get_neighbors("n1", relation_type="supports")
        assert len(supports_only) == 1
        assert supports_only[0].node_id == "n2"

    def test_get_subgraph(self, lt_graph: LongTermMemoryGraph) -> None:
        # n1 -> n2 -> n3 -> n4
        for i in range(1, 5):
            lt_graph.add_node(MemoryNode(node_id=f"n{i}", content=f"node {i}"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="r"))
        lt_graph.add_edge(MemoryEdge(source_id="n2", target_id="n3", relation_type="r"))
        lt_graph.add_edge(MemoryEdge(source_id="n3", target_id="n4", relation_type="r"))

        # depth=1 from n1 -> should get n1, n2
        nodes, _ = lt_graph.get_subgraph("n1", depth=1)
        node_ids = {n.node_id for n in nodes}
        assert node_ids == {"n1", "n2"}

        # depth=2 from n1 -> should get n1, n2, n3
        nodes, _ = lt_graph.get_subgraph("n1", depth=2)
        node_ids = {n.node_id for n in nodes}
        assert node_ids == {"n1", "n2", "n3"}

    def test_save_load_persistence(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="fact A", tags=["tag1"]))
        lt_graph.add_node(MemoryNode(node_id="n2", content="fact B"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="supports"))
        lt_graph.save()

        # Load into a new graph instance
        graph2 = LongTermMemoryGraph(storage_path=lt_graph._storage_path.as_posix())
        graph2.load()
        assert graph2.node_count() == 2
        assert graph2.edge_count() == 1
        n1 = graph2.get_node("n1")
        assert n1 is not None
        assert n1.content == "fact A"
        assert n1.tags == ["tag1"]

    def test_record_access(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a"))
        assert lt_graph.get_node("n1").access_count == 0  # type: ignore[union-attr]  expiry_wave: permanent
        lt_graph.record_access("n1")
        lt_graph.record_access("n1")
        assert lt_graph.get_node("n1").access_count == 2  # type: ignore[union-attr]  expiry_wave: permanent

    def test_node_and_edge_count(self, lt_graph: LongTermMemoryGraph) -> None:
        assert lt_graph.node_count() == 0
        assert lt_graph.edge_count() == 0
        lt_graph.add_node(MemoryNode(node_id="n1", content="a"))
        lt_graph.add_node(MemoryNode(node_id="n2", content="b"))
        lt_graph.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="r"))
        assert lt_graph.node_count() == 2
        assert lt_graph.edge_count() == 1

    def test_search_empty_query(self, lt_graph: LongTermMemoryGraph) -> None:
        lt_graph.add_node(MemoryNode(node_id="n1", content="a"))
        assert lt_graph.search("") == []
        assert lt_graph.search("   ") == []

    def test_get_subgraph_nonexistent(self, lt_graph: LongTermMemoryGraph) -> None:
        nodes, edges = lt_graph.get_subgraph("nonexistent")
        assert nodes == []
        assert edges == []


class TestLongTermConsolidator:
    def test_extracts_facts_from_daily_summaries(
        self, mt_store: MidTermMemoryStore, lt_graph: LongTermMemoryGraph
    ) -> None:
        mt_store.save(
            DailySummary(
                date="2026-04-07",
                sessions_count=2,
                tasks_completed=["built feature X"],
                key_learnings=["caching improves perf", "use retry on timeout"],
                patterns_observed=["grep used frequently"],
            )
        )
        consolidator = LongTermConsolidator(mt_store, lt_graph)
        count = consolidator.consolidate(days=7)

        assert count > 0
        assert lt_graph.node_count() > 0
        # Should have fact nodes for learnings and completed tasks
        facts = lt_graph.search_by_type("fact")
        assert any("caching" in n.content for n in facts)
        # Should have pattern nodes
        patterns = lt_graph.search_by_type("pattern")
        assert any("grep" in n.content for n in patterns)

    def test_merge_duplicates(
        self, mt_store: MidTermMemoryStore, lt_graph: LongTermMemoryGraph
    ) -> None:
        # Add duplicate nodes manually
        lt_graph.add_node(MemoryNode(node_id="n1", content="caching improves perf", confidence=0.5))
        lt_graph.add_node(MemoryNode(node_id="n2", content="caching improves perf", confidence=0.9))

        consolidator = LongTermConsolidator(mt_store, lt_graph)
        merged = consolidator._merge_duplicates()
        assert merged == 1
        assert lt_graph.node_count() == 1
        # Keeper should have higher confidence
        remaining = next(iter(lt_graph._nodes.values()))
        assert remaining.confidence == 0.9


# ===========================================================================
# Unified Retriever
# ===========================================================================


class TestUnifiedRetriever:
    def test_retrieve_allocates_budget(
        self,
        tmp_path: Any,
    ) -> None:
        st = ShortTermMemoryStore(str(tmp_path / "st"))
        mt = MidTermMemoryStore(str(tmp_path / "mt"))
        lt = LongTermMemoryGraph(str(tmp_path / "lt" / "g.json"))

        # Populate stores
        st.save(
            ShortTermMemory(
                session_id="s1",
                run_id="r1",
                task_goal="analyze code",
                key_findings=["found bug"],
                created_at="2026-04-07T10:00:00+00:00",
            )
        )
        mt.save(
            DailySummary(
                date="2026-04-07",
                sessions_count=1,
                key_learnings=["use tests"],
            )
        )
        lt.add_node(
            MemoryNode(
                node_id="n1",
                content="code analysis requires static tools",
                tags=["code", "analysis"],
            )
        )

        retriever = UnifiedMemoryRetriever(
            short_term=st, mid_term=mt, long_term=lt, budget_tokens=2000
        )
        ctx = retriever.retrieve(query="code analysis")

        assert len(ctx.long_term_items) >= 1
        assert len(ctx.mid_term_items) >= 1
        assert len(ctx.short_term_items) >= 1
        assert ctx.total_tokens > 0

    def test_retrieve_for_stage_with_failures(
        self,
        tmp_path: Any,
    ) -> None:
        lt = LongTermMemoryGraph(str(tmp_path / "lt" / "g.json"))
        lt.add_node(
            MemoryNode(
                node_id="n1",
                content="missing_evidence often means insufficient search",
                tags=["missing_evidence", "error"],
            )
        )

        retriever = UnifiedMemoryRetriever(long_term=lt, budget_tokens=2000)
        ctx = retriever.retrieve_for_stage(
            stage_id="S2",
            task_family="code_review",
            current_failures=["missing_evidence"],
        )
        # With failures, long-term gets boosted budget (60%)
        assert len(ctx.long_term_items) >= 1
        assert "missing_evidence" in ctx.long_term_items[0]

    def test_memory_context_to_context_string(self) -> None:
        ctx = MemoryContext(
            long_term_items=["[fact] Python uses GIL"],
            mid_term_items=["[Daily 2026-04-07] 3 sessions"],
            short_term_items=["[Session s1] completed: analyze code"],
        )
        text = ctx.to_context_string()
        assert "Long-term Knowledge" in text
        assert "Recent Daily Context" in text
        assert "Current Session" in text
        assert "Python uses GIL" in text

    def test_memory_context_to_sections(self) -> None:
        ctx = MemoryContext(
            long_term_items=["item A"],
            mid_term_items=["item B"],
            short_term_items=["item C"],
        )
        sections = ctx.to_sections()
        assert "item A" in sections["long_term"]
        assert "item B" in sections["mid_term"]
        assert "item C" in sections["short_term"]

    def test_graceful_degradation_none_tiers(self) -> None:
        retriever = UnifiedMemoryRetriever(
            short_term=None, mid_term=None, long_term=None, budget_tokens=2000
        )
        ctx = retriever.retrieve(query="anything")
        assert ctx.long_term_items == []
        assert ctx.mid_term_items == []
        assert ctx.short_term_items == []
        assert ctx.total_tokens == 0

    def test_retrieve_for_stage_no_failures(
        self,
        tmp_path: Any,
    ) -> None:
        lt = LongTermMemoryGraph(str(tmp_path / "lt" / "g.json"))
        lt.add_node(MemoryNode(node_id="n1", content="S1 understand stage tips", tags=["S1"]))
        retriever = UnifiedMemoryRetriever(long_term=lt, budget_tokens=2000)
        ctx = retriever.retrieve_for_stage(stage_id="S1", task_family="analysis")
        # Uses normal budget allocation (40% long-term)
        assert len(ctx.long_term_items) >= 1

    def test_empty_context_string(self) -> None:
        ctx = MemoryContext()
        assert ctx.to_context_string() == ""

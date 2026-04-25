"""Tests for automatic knowledge ingestion from session after run completion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.knowledge_manager import KnowledgeManager
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
from hi_agent.knowledge.wiki import KnowledgeWiki
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.memory.long_term import LongTermMemoryGraph
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeSession:
    """Minimal session stub exposing the attributes ingest_from_session reads."""

    run_id: str = "fake-run"
    findings: list[str] = field(default_factory=list)
    user_feedback: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)


def _make_executor(
    tmp_path,
    *,
    knowledge_manager: KnowledgeManager | None = None,
    session: Any = None,
    force_fail: bool = False,
) -> RunExecutor:
    constraints: list[str] = []
    if force_fail:
        constraints.append("fail_action:analyze_goal")
    contract = TaskContract(
        task_id="kc-test",
        goal="knowledge creation test",
        task_family="quick_task",
        constraints=constraints,
    )
    kernel = MockKernel()
    return RunExecutor(
        contract,
        kernel,
        knowledge_manager=knowledge_manager,
        session=session,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_knowledge_ingested_after_successful_run(tmp_path) -> None:
    """KnowledgeManager.ingest_from_session is called on completed run."""
    _kdir = str(tmp_path / "knowledge")
    _graph = LongTermMemoryGraph(f"{_kdir}/graph.json")
    km = KnowledgeManager(
        wiki=KnowledgeWiki(f"{_kdir}/wiki"),
        user_store=UserKnowledgeStore(f"{_kdir}/user"),
        graph=_graph,
        renderer=GraphRenderer(_graph),
    )
    session = FakeSession(
        findings=["Revenue grew 12% YoY"],
        user_feedback=["prefer charts over tables"],
        facts=[{"content": "Q4 is strongest quarter", "type": "fact", "tags": ["finance"]}],
    )
    executor = _make_executor(tmp_path, knowledge_manager=km, session=session)
    result = executor.execute()

    assert result == "completed"
    stats = km.get_stats()
    # 1 finding wiki page + 1 fact graph node = at minimum 2 items
    assert stats["wiki_pages"] >= 1
    assert stats["graph_nodes"] >= 1


def test_knowledge_ingested_after_failed_run(tmp_path) -> None:
    """KnowledgeManager.ingest_from_session is called even when run fails."""
    _kdir = str(tmp_path / "knowledge")
    _graph = LongTermMemoryGraph(f"{_kdir}/graph.json")
    km = KnowledgeManager(
        wiki=KnowledgeWiki(f"{_kdir}/wiki"),
        user_store=UserKnowledgeStore(f"{_kdir}/user"),
        graph=_graph,
        renderer=GraphRenderer(_graph),
    )
    session = FakeSession(
        findings=["Partial analysis completed before failure"],
    )
    executor = _make_executor(
        tmp_path,
        knowledge_manager=km,
        session=session,
        force_fail=True,
    )
    result = executor.execute()

    assert result == "failed"
    stats = km.get_stats()
    assert stats["wiki_pages"] >= 1


def test_ingested_items_in_wiki_and_graph(tmp_path) -> None:
    """Ingested findings appear as wiki pages; facts appear in graph."""
    _kdir = str(tmp_path / "knowledge")
    _graph = LongTermMemoryGraph(f"{_kdir}/graph.json")
    km = KnowledgeManager(
        wiki=KnowledgeWiki(f"{_kdir}/wiki"),
        user_store=UserKnowledgeStore(f"{_kdir}/user"),
        graph=_graph,
        renderer=GraphRenderer(_graph),
    )
    session = FakeSession(
        findings=["Insight A", "Insight B"],
        facts=[
            {"content": "Fact 1", "type": "fact", "tags": ["t1"]},
            {"content": "Fact 2", "type": "method", "tags": ["t2"]},
        ],
    )
    executor = _make_executor(tmp_path, knowledge_manager=km, session=session)
    executor.execute()

    # Wiki should contain both findings
    pages = km.wiki.list_pages()
    assert len(pages) >= 2
    titles = [p.title for p in pages]
    assert "Insight A" in titles
    assert "Insight B" in titles

    # Graph should contain both facts
    assert km.graph.node_count() >= 2
    nodes = km.graph.search("Fact", limit=10)
    contents = [n.content for n in nodes]
    assert "Fact 1" in contents
    assert "Fact 2" in contents


def test_user_feedback_stored(tmp_path) -> None:
    """User feedback from session is ingested into user knowledge store."""
    _kdir = str(tmp_path / "knowledge")
    _graph = LongTermMemoryGraph(f"{_kdir}/graph.json")
    km = KnowledgeManager(
        wiki=KnowledgeWiki(f"{_kdir}/wiki"),
        user_store=UserKnowledgeStore(f"{_kdir}/user"),
        graph=_graph,
        renderer=GraphRenderer(_graph),
    )
    session = FakeSession(
        user_feedback=["I prefer concise summaries", "Use metric units"],
    )
    executor = _make_executor(tmp_path, knowledge_manager=km, session=session)
    executor.execute()

    profile = km.user_store.get_profile()
    assert len(profile.feedback_history) >= 2
    assert "I prefer concise summaries" in profile.feedback_history


def test_backward_compat_no_knowledge_manager(tmp_path) -> None:
    """knowledge_manager=None (default) does not cause errors."""
    executor = _make_executor(tmp_path, knowledge_manager=None)
    result = executor.execute()
    assert result == "completed"


def test_backward_compat_no_session(tmp_path) -> None:
    """Even with knowledge_manager set, None session is safe."""
    _kdir = str(tmp_path / "knowledge")
    _graph = LongTermMemoryGraph(f"{_kdir}/graph.json")
    km = KnowledgeManager(
        wiki=KnowledgeWiki(f"{_kdir}/wiki"),
        user_store=UserKnowledgeStore(f"{_kdir}/user"),
        graph=_graph,
        renderer=GraphRenderer(_graph),
    )
    contract = TaskContract(task_id="kc-nosess", goal="no session test")
    kernel = MockKernel()
    # Explicitly pass session=None and suppress auto-creation by using
    # a knowledge_manager but no session object.
    executor = RunExecutor(
        contract,
        kernel,
        knowledge_manager=km,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    # Session is auto-created in __init__; the ingest will just find
    # no findings/facts/user_feedback �?count=0, no error.
    result = executor.execute()
    assert result == "completed"
    # Should have ingested 0 items (auto-created session has no findings).
    stats = km.get_stats()
    assert stats["wiki_pages"] == 0
    assert stats["graph_nodes"] == 0

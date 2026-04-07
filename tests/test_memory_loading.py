"""Tests for memory loading: RetrievalEngine feeds knowledge into routing context."""

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.knowledge.retrieval_engine import RetrievalEngine, RetrievalResult
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.mock_kernel import MockKernel


def _make_wiki() -> KnowledgeWiki:
    """Create a small wiki with test pages."""
    wiki = KnowledgeWiki(wiki_dir=".hi_agent_test/wiki")
    wiki.add_page(WikiPage(
        page_id="revenue-q4",
        title="Revenue Analysis Q4",
        content="Q4 revenue was $10M, up 20% from Q3. Key drivers: cloud and SaaS.",
        tags=["revenue", "quarterly", "analysis"],
    ))
    wiki.add_page(WikiPage(
        page_id="cost-analysis",
        title="Cost Analysis",
        content="Operating costs rose 5% due to hiring. Margins improved overall.",
        tags=["cost", "analysis"],
    ))
    return wiki


def _make_graph() -> LongTermMemoryGraph:
    """Create a small graph with test nodes."""
    graph = LongTermMemoryGraph(storage_path=".hi_agent_test/graph.json")
    graph.add_node(MemoryNode(
        node_id="entity-revenue",
        content="Revenue entity: tracks quarterly financial data",
        node_type="entity",
        tags=["revenue", "finance"],
    ))
    return graph


def _make_retrieval_engine() -> RetrievalEngine:
    """Build a RetrievalEngine with wiki and graph for testing."""
    wiki = _make_wiki()
    graph = _make_graph()
    renderer = GraphRenderer(graph)
    engine = RetrievalEngine(
        wiki=wiki,
        graph=graph,
        graph_renderer=renderer,
    )
    engine.build_index()
    return engine


def test_backward_compat_no_retrieval_engine() -> None:
    """RunExecutor with retrieval_engine=None should work without error."""
    contract = TaskContract(task_id="compat-001", goal="backward compat test")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel)
    assert executor.retrieval_engine is None
    result = executor.execute()
    assert result == "completed"


def test_retrieval_engine_stored() -> None:
    """retrieval_engine param should be stored on the executor."""
    engine = _make_retrieval_engine()
    contract = TaskContract(task_id="store-001", goal="store test")
    kernel = MockKernel()
    executor = RunExecutor(contract, kernel, retrieval_engine=engine)
    assert executor.retrieval_engine is engine


def test_knowledge_retrieved_event_injected() -> None:
    """RunExecutor with retrieval_engine should inject knowledge_retrieved events."""
    engine = _make_retrieval_engine()
    contract = TaskContract(
        task_id="retrieve-001",
        goal="Analyze quarterly revenue data",
        task_family="quick_task",
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, retrieval_engine=engine)

    result = executor.execute()
    assert result == "completed"

    # Check session has knowledge_retrieved events
    assert executor.session is not None
    kr_records = [
        r for r in executor.session.l0_records
        if r["event_type"] == "knowledge_retrieved"
    ]
    # Should have at least one knowledge_retrieved record (for stages that match)
    assert len(kr_records) > 0
    # Each record should contain stage_id, items count, tokens
    for rec in kr_records:
        payload = rec["payload"]
        assert "stage_id" in payload
        assert "items" in payload
        assert "tokens" in payload
        assert payload["items"] > 0


def test_retrieval_called_per_stage() -> None:
    """Retrieval engine should be called once per stage during execution."""
    call_count = 0
    original_engine = _make_retrieval_engine()

    class CountingEngine:
        """Wrapper that counts retrieve() calls."""
        def retrieve(self, query, budget_tokens=2000):
            nonlocal call_count
            call_count += 1
            return original_engine.retrieve(query, budget_tokens=budget_tokens)

    contract = TaskContract(
        task_id="count-001",
        goal="Analyze quarterly revenue data",
        task_family="quick_task",
    )
    kernel = MockKernel(strict_mode=True)
    counting = CountingEngine()
    executor = RunExecutor(contract, kernel, retrieval_engine=counting)

    executor.execute()

    # Should be called at least once per stage (5 stages) for the
    # pre-propose injection; the enriched context provider may add more.
    assert call_count >= 5


def test_enriched_context_includes_retrieved_knowledge() -> None:
    """When retrieval_engine is set, route engine context should include retrieved_knowledge."""
    engine = _make_retrieval_engine()
    contract = TaskContract(
        task_id="enrich-001",
        goal="Analyze quarterly revenue data",
        task_family="quick_task",
    )
    kernel = MockKernel()
    executor = RunExecutor(contract, kernel, retrieval_engine=engine)

    # The enriched context provider should be wired to the route engine
    if hasattr(executor.route_engine, '_context_provider'):
        # Set stage so the query has content
        if executor.session is not None:
            executor.session.current_stage = "S1_understand"
        ctx = executor.route_engine._context_provider()
        assert isinstance(ctx, dict)
        # Should contain retrieved_knowledge if the engine found matches
        # (our wiki has "revenue" and "analysis" which match the goal)
        assert "retrieved_knowledge" in ctx
        assert len(ctx["retrieved_knowledge"]) > 0
        # Each item should be a string (content[:200])
        for item in ctx["retrieved_knowledge"]:
            assert isinstance(item, str)
            assert len(item) <= 200


def test_enriched_context_fallback_on_no_results() -> None:
    """If retrieval returns no items, context should still work without retrieved_knowledge."""
    # Empty engine with no data
    engine = RetrievalEngine()
    engine.build_index()

    contract = TaskContract(
        task_id="empty-001",
        goal="zzz no match xyz",
        task_family="quick_task",
    )
    kernel = MockKernel()
    executor = RunExecutor(contract, kernel, retrieval_engine=engine)

    if hasattr(executor.route_engine, '_context_provider'):
        if executor.session is not None:
            executor.session.current_stage = "S1_understand"
        ctx = executor.route_engine._context_provider()
        assert isinstance(ctx, dict)
        # Should still be a valid context dict even without retrieved_knowledge
        assert "contract" in ctx


def test_retrieval_engine_error_does_not_break_execution() -> None:
    """If retrieval engine raises, execution should still complete."""

    class BrokenEngine:
        def retrieve(self, query, budget_tokens=2000):
            raise RuntimeError("retrieval failed")

    contract = TaskContract(
        task_id="broken-001",
        goal="test broken retrieval",
        task_family="quick_task",
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, retrieval_engine=BrokenEngine())

    result = executor.execute()
    assert result == "completed"

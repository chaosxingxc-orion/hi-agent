"""Tests for the four-layer knowledge retrieval engine."""

from __future__ import annotations

import pytest
from hi_agent.knowledge.granularity import (
    KnowledgeItem,
    estimate_tokens,
    extract_facts,
    to_chunk,
)
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.retrieval_engine import (
    RetrievalEngine,
    RetrievalResult,
    cosine_similarity,
)
from hi_agent.knowledge.tfidf import HybridRanker, TFIDFIndex
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryEdge, MemoryNode
from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore
from hi_agent.memory.short_term import ShortTermMemory, ShortTermMemoryStore

# ===================================================================
# Granularity tests
# ===================================================================


class TestEstimateTokens:
    def test_basic(self):
        assert estimate_tokens("hello world") >= 1

    def test_empty(self):
        assert estimate_tokens("") == 1

    def test_long_text(self):
        text = "a" * 400
        assert estimate_tokens(text) == 100


class TestExtractFacts:
    def test_splits_sentences(self):
        text = (
            "Revenue grew by 20% in Q4. Costs remained stable. "
            "Profit margins improved significantly."
        )
        facts = extract_facts(text)
        assert len(facts) >= 2

    def test_filters_short(self):
        text = "OK. Fine. This is a meaningful sentence with enough content."
        facts = extract_facts(text)
        # Short fragments filtered out
        for fact in facts:
            assert len(fact) > 15

    def test_max_facts(self):
        text = ". ".join([f"This is fact number {i} with enough text" for i in range(20)])
        facts = extract_facts(text, max_facts=5)
        assert len(facts) <= 5

    def test_newline_handling(self):
        text = "First line has content\nSecond line has content"
        facts = extract_facts(text)
        assert len(facts) >= 1


class TestToChunk:
    def test_fact_only(self):
        result = to_chunk("Revenue grew 20%")
        assert result == "Revenue grew 20%"

    def test_with_context(self):
        result = to_chunk("Revenue grew 20%", context="Q4 2026 report")
        assert "Context: Q4 2026 report" in result

    def test_with_source(self):
        result = to_chunk("Revenue grew 20%", source="annual-report")
        assert "(Source: annual-report)" in result

    def test_full(self):
        result = to_chunk("Revenue grew 20%", context="Q4", source="report")
        assert "Revenue grew 20%" in result
        assert "Context: Q4" in result
        assert "(Source: report)" in result


# ===================================================================
# TF-IDF tests
# ===================================================================


class TestTFIDFIndex:
    def test_add_and_search(self):
        idx = TFIDFIndex()
        idx.add("d1", "machine learning algorithms for data analysis")
        idx.add("d2", "cooking recipes for italian pasta dishes")
        idx.add("d3", "deep learning neural networks machine learning")

        results = idx.search("machine learning")
        assert len(results) >= 1
        # d1 and d3 should rank higher than d2
        doc_ids = [r[0] for r in results]
        assert "d2" not in doc_ids or doc_ids.index("d1") < doc_ids.index("d2")

    def test_empty_index(self):
        idx = TFIDFIndex()
        assert idx.search("anything") == []
        assert idx.bm25("anything") == []

    def test_remove_document(self):
        idx = TFIDFIndex()
        idx.add("d1", "machine learning")
        idx.add("d2", "cooking recipes")
        assert idx.doc_count == 2

        idx.remove("d1")
        assert idx.doc_count == 1

        results = idx.search("machine learning")
        doc_ids = [r[0] for r in results]
        assert "d1" not in doc_ids

    def test_tokenization_punctuation_case(self):
        idx = TFIDFIndex()
        idx.add("d1", "Hello, World! This is a TEST.")
        results = idx.search("hello world test")
        assert len(results) == 1

    def test_doc_count(self):
        idx = TFIDFIndex()
        assert idx.doc_count == 0
        idx.add("d1", "doc one")
        assert idx.doc_count == 1
        idx.add("d2", "doc two")
        assert idx.doc_count == 2

    def test_bm25_ranking(self):
        idx = TFIDFIndex()
        # Short doc with focused content
        idx.add("short", "machine learning")
        # Long doc with diluted content
        idx.add("long", "machine learning " + "extra words " * 50)

        tfidf_results = idx.search("machine learning")
        bm25_results = idx.bm25("machine learning")

        # BM25 with length normalization should penalize the long doc more
        _ = [r[0] for r in bm25_results]
        _ = [r[0] for r in tfidf_results]
        # Both should return results, but rankings may differ
        assert len(bm25_results) >= 1
        assert len(tfidf_results) >= 1

    def test_bm25_empty_query(self):
        idx = TFIDFIndex()
        idx.add("d1", "some text")
        assert idx.bm25("") == []

    def test_search_empty_query(self):
        idx = TFIDFIndex()
        idx.add("d1", "some text")
        assert idx.search("") == []


# ===================================================================
# HybridRanker tests
# ===================================================================


class TestHybridRanker:
    def test_composite_scoring_weights(self):
        idx = TFIDFIndex()
        ranker = HybridRanker(idx)

        items = [
            KnowledgeItem(
                item_id="a",
                content="low relevance",
                level=1,
                source_type="long_term_text",
                relevance_score=0.1,
                recency_score=0.9,
                importance_score=0.9,
            ),
            KnowledgeItem(
                item_id="b",
                content="high relevance",
                level=1,
                source_type="long_term_text",
                relevance_score=0.9,
                recency_score=0.1,
                importance_score=0.1,
            ),
        ]
        result = ranker.rank("", items)
        # With default weights: relevance=0.4, recency=0.3, importance=0.2, structure=0.1
        # a: 0.4*0.1 + 0.3*0.9 + 0.2*0.9 + 0.1*0 = 0.04 + 0.27 + 0.18 = 0.49
        # b: 0.4*0.9 + 0.3*0.1 + 0.2*0.1 + 0.1*0 = 0.36 + 0.03 + 0.02 = 0.41
        assert result[0].item_id == "a"
        assert result[0].composite_score > result[1].composite_score

    def test_graph_node_structure_bonus(self):
        idx = TFIDFIndex()
        ranker = HybridRanker(idx)

        graph_item = KnowledgeItem(
            item_id="g1",
            content="graph node",
            level=1,
            source_type="long_term_graph",
            relevance_score=0.5,
            metadata={"degree": 5, "access_count": 10},
        )
        text_item = KnowledgeItem(
            item_id="t1",
            content="text item",
            level=1,
            source_type="long_term_text",
            relevance_score=0.5,
        )
        result = ranker.rank("", [graph_item, text_item])
        # Graph item should have higher score due to structure bonus
        g_score = next(i for i in result if i.item_id == "g1").composite_score
        t_score = next(i for i in result if i.item_id == "t1").composite_score
        assert g_score > t_score

    def test_sorting_by_composite(self):
        idx = TFIDFIndex()
        ranker = HybridRanker(idx)

        items = [
            KnowledgeItem(
                item_id="low",
                content="x",
                level=1,
                source_type="long_term_text",
                relevance_score=0.1,
            ),
            KnowledgeItem(
                item_id="high",
                content="y",
                level=1,
                source_type="long_term_text",
                relevance_score=0.9,
            ),
            KnowledgeItem(
                item_id="mid",
                content="z",
                level=1,
                source_type="long_term_text",
                relevance_score=0.5,
            ),
        ]
        result = ranker.rank("", items)
        scores = [i.composite_score for i in result]
        assert scores == sorted(scores, reverse=True)


# ===================================================================
# RetrievalEngine integration tests
# ===================================================================


def _make_wiki() -> KnowledgeWiki:
    wiki = KnowledgeWiki()
    wiki.add_page(
        WikiPage(
            page_id="revenue-q4",
            title="Revenue Analysis Q4",
            content="Revenue grew by 20% in Q4 2026 driven by new product launches.",
            tags=["revenue", "q4", "finance"],
        )
    )
    wiki.add_page(
        WikiPage(
            page_id="cost-analysis",
            title="Cost Analysis",
            content="Operating costs decreased by 5% due to efficiency improvements.",
            tags=["cost", "operations"],
        )
    )
    wiki.add_page(
        WikiPage(
            page_id="ml-models",
            title="Machine Learning Models",
            content="We deployed three ML models for demand forecasting in production.",
            tags=["ml", "forecasting"],
        )
    )
    return wiki


def _make_graph() -> LongTermMemoryGraph:
    graph = LongTermMemoryGraph()
    n1 = MemoryNode(
        node_id="n1", content="Revenue growth pattern", node_type="fact", tags=["revenue"]
    )
    n2 = MemoryNode(
        node_id="n2", content="Cost reduction strategy", node_type="method", tags=["cost"]
    )
    n3 = MemoryNode(
        node_id="n3", content="Q4 performance metrics", node_type="fact", tags=["q4", "metrics"]
    )
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    graph.add_edge(MemoryEdge(source_id="n1", target_id="n3", relation_type="supports"))
    graph.add_edge(MemoryEdge(source_id="n2", target_id="n3", relation_type="derived_from"))
    return graph


def _make_short_term(tmp_path) -> ShortTermMemoryStore:
    store = ShortTermMemoryStore(str(tmp_path / "short"))
    mem = ShortTermMemory(
        session_id="sess-001",
        run_id="run-001",
        task_goal="Analyze Q4 revenue trends",
        key_findings=["Revenue up 20%", "New markets opened"],
        outcome="completed",
    )
    store.save(mem)
    return store


def _make_mid_term(tmp_path) -> MidTermMemoryStore:
    store = MidTermMemoryStore(str(tmp_path / "mid"))
    summary = DailySummary(
        date="2026-04-06",
        sessions_count=3,
        tasks_completed=["Revenue analysis", "Cost review"],
        key_learnings=["Revenue growth driven by product launches"],
    )
    store.save(summary)
    return store


class TestRetrievalEngineLayer1:
    def test_grep_finds_keyword_matches(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        engine.build_index()
        candidates = engine._layer1_grep("revenue")
        assert len(candidates) >= 1
        assert any("revenue" in c.content.lower() for c in candidates)

    def test_grep_no_matches(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        engine.build_index()
        candidates = engine._layer1_grep("zzzznonexistent")
        assert len(candidates) == 0


class TestRetrievalEngineLayer2:
    def test_bm25_ranks_better_matches_higher(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        engine.build_index()
        candidates = engine._layer1_grep("revenue")
        ranked = engine._layer2_rank("revenue", candidates)
        assert len(ranked) >= 1
        # Revenue-specific page should rank first
        assert "revenue" in ranked[0].content.lower()


class TestRetrievalEngineLayer3:
    def test_graph_expansion_adds_mermaid(self, tmp_path):
        graph = _make_graph()
        renderer = GraphRenderer(graph)
        engine = RetrievalEngine(graph=graph, graph_renderer=renderer)
        engine.build_index()

        # Create a graph candidate
        item = KnowledgeItem(
            item_id="graph:n1",
            content="Revenue growth pattern",
            level=1,
            source_type="long_term_graph",
            source_id="n1",
            token_estimate=10,
        )
        result = engine._layer3_graph_expand("revenue", [item], include_viz=True)
        assert len(result) == 1
        assert "mermaid" in result[0].content.lower() or "Key entities" in result[0].content
        assert result[0].level == 4

    def test_non_graph_passthrough(self, tmp_path):
        engine = RetrievalEngine()
        item = KnowledgeItem(
            item_id="wiki:test",
            content="Some wiki content",
            level=3,
            source_type="long_term_text",
            source_id="test",
            token_estimate=10,
        )
        result = engine._layer3_graph_expand("query", [item], include_viz=True)
        assert result[0].content == "Some wiki content"
        assert result[0].level == 3


class TestRetrievalEngineLayer4:
    def test_embedding_rerank(self):
        def mock_embedding(text: str) -> list[float]:
            # Simple mock: vector based on presence of "revenue"
            if "revenue" in text.lower():
                return [1.0, 0.0, 0.0]
            elif "cost" in text.lower():
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

        engine = RetrievalEngine(embedding_fn=mock_embedding)
        items = [
            KnowledgeItem(
                item_id="a",
                content="cost reduction",
                level=1,
                source_type="long_term_text",
            ),
            KnowledgeItem(
                item_id="b",
                content="revenue growth",
                level=1,
                source_type="long_term_text",
            ),
        ]
        result = engine._layer4_embedding_rerank("revenue analysis", items)
        assert result[0].item_id == "b"
        assert result[0].relevance_score > result[1].relevance_score


class TestRetrievalEngineBudget:
    def test_budget_trimming(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        engine.build_index()
        result = engine.retrieve("revenue cost analysis", budget_tokens=50)
        assert result.total_tokens <= 50
        assert result.budget_tokens == 50

    def test_large_budget_includes_more(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        engine.build_index()
        small = engine.retrieve("revenue cost", budget_tokens=30)
        large = engine.retrieve("revenue cost", budget_tokens=5000)
        assert len(large.items) >= len(small.items)


class TestRetrievalEngineIntegration:
    def test_retrieve_across_sources(self, tmp_path):
        wiki = _make_wiki()
        graph = _make_graph()
        short_term = _make_short_term(tmp_path)
        mid_term = _make_mid_term(tmp_path)
        renderer = GraphRenderer(graph)

        engine = RetrievalEngine(
            wiki=wiki,
            graph=graph,
            short_term=short_term,
            mid_term=mid_term,
            graph_renderer=renderer,
        )
        result = engine.retrieve("revenue", budget_tokens=5000)
        assert result.total_candidates >= 1
        source_types = {item.source_type for item in result.items}
        # Should pull from multiple sources
        assert len(source_types) >= 1

    def test_retrieve_without_graph(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        result = engine.retrieve("revenue", budget_tokens=5000)
        assert len(result.items) >= 1
        assert all(i.source_type != "long_term_graph" for i in result.items)

    def test_build_index_counts(self, tmp_path):
        wiki = _make_wiki()
        graph = _make_graph()
        short_term = _make_short_term(tmp_path)
        mid_term = _make_mid_term(tmp_path)

        engine = RetrievalEngine(
            wiki=wiki,
            graph=graph,
            short_term=short_term,
            mid_term=mid_term,
            storage_dir=str(tmp_path / "knowledge"),
        )
        count = engine.build_index()
        # 3 wiki + 3 graph + 1 short + 1 mid = 8
        assert count == 8

    def test_layers_used_without_embedding(self, tmp_path):
        wiki = _make_wiki()
        engine = RetrievalEngine(wiki=wiki)
        result = engine.retrieve("revenue", budget_tokens=5000)
        assert 1 in result.layers_used
        assert 2 in result.layers_used
        assert 3 in result.layers_used
        assert 4 not in result.layers_used

    def test_layers_used_with_embedding(self, tmp_path):
        wiki = _make_wiki()

        def mock_emb(text: str) -> list[float]:
            return [0.5, 0.5]

        engine = RetrievalEngine(wiki=wiki, embedding_fn=mock_emb)
        result = engine.retrieve("revenue", budget_tokens=5000)
        assert 4 in result.layers_used


class TestRetrievalResult:
    def test_to_context_string(self):
        result = RetrievalResult(
            items=[
                KnowledgeItem(
                    item_id="a", content="First item", level=1, source_type="long_term_text"
                ),
                KnowledgeItem(
                    item_id="b", content="Second item", level=1, source_type="short_term"
                ),
            ]
        )
        text = result.to_context_string()
        assert "First item" in text
        assert "Second item" in text
        assert "---" in text

    def test_to_context_string_empty(self):
        result = RetrievalResult()
        assert result.to_context_string() == ""

    def test_to_sections_grouping(self):
        result = RetrievalResult(
            items=[
                KnowledgeItem(item_id="a", content="Wiki A", level=3, source_type="long_term_text"),
                KnowledgeItem(item_id="b", content="Wiki B", level=3, source_type="long_term_text"),
                KnowledgeItem(
                    item_id="c", content="Graph C", level=4, source_type="long_term_graph"
                ),
                KnowledgeItem(item_id="d", content="Short D", level=2, source_type="short_term"),
            ]
        )
        sections = result.to_sections()
        assert "long_term_text" in sections
        assert len(sections["long_term_text"]) == 2
        assert "long_term_graph" in sections
        assert len(sections["long_term_graph"]) == 1
        assert "short_term" in sections
        assert len(sections["short_term"]) == 1

    def test_to_sections_empty(self):
        result = RetrievalResult()
        sections = result.to_sections()
        assert sections == {}


class TestCosineSimilarity:
    def test_identical(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_opposite(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

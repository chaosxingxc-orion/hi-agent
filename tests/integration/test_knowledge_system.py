"""Tests for the knowledge management system: wiki, user knowledge, graph renderer, manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.knowledge_manager import KnowledgeManager, KnowledgeResult
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore, UserProfile
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryEdge, MemoryNode

# ======================================================================
# WikiPage & KnowledgeWiki tests
# ======================================================================


class TestWikiPage:
    def test_creation_with_wikilinks(self) -> None:
        page = WikiPage(
            page_id="test-page",
            title="Test Page",
            content="See [[other-page]] and [[third-page]] for details.",
        )
        assert page.page_id == "test-page"
        assert page.title == "Test Page"
        assert "[[other-page]]" in page.content
        assert page.page_type == "concept"
        assert page.confidence == 1.0

    def test_default_fields(self) -> None:
        page = WikiPage(page_id="p", title="P", content="text")
        assert page.tags == []
        assert page.sources == []
        assert page.outgoing_links == []
        assert page.created_at == ""
        assert page.updated_at == ""


class TestKnowledgeWiki:
    def test_add_and_get_page(self) -> None:
        wiki = KnowledgeWiki()
        page = WikiPage(page_id="alpha", title="Alpha", content="Alpha content.")
        wiki.add_page(page)
        result = wiki.get_page("alpha")
        assert result is not None, f"Expected non-None result for result"
        assert result.title == "Alpha"
        assert result.created_at != ""

    def test_search_by_keyword(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(
            WikiPage(page_id="a", title="Revenue Analysis", content="Q4 revenue grew 20%.")
        )
        wiki.add_page(WikiPage(page_id="b", title="Cost Report", content="Costs increased."))
        wiki.add_page(
            WikiPage(page_id="c", title="Revenue Forecast", content="Revenue expected to grow.")
        )

        results = wiki.search("revenue")
        assert len(results) >= 2
        titles = [r.title for r in results]
        assert "Revenue Analysis" in titles
        assert "Revenue Forecast" in titles

    def test_search_empty_query(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="x", title="X", content="stuff"))
        assert wiki.search("") == []
        assert wiki.search("   ") == []

    def test_remove_page(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="del", title="Delete Me", content="gone"))
        assert wiki.get_page("del") is not None
        wiki.remove_page("del")
        assert wiki.get_page("del") is None

    def test_remove_nonexistent(self) -> None:
        wiki = KnowledgeWiki()
        wiki.remove_page("nope")  # should not raise

    def test_extract_links(self) -> None:
        links = KnowledgeWiki.extract_links("See [[page-a]] and [[page-b]] for info.")
        assert links == ["page-a", "page-b"]

    def test_extract_links_empty(self) -> None:
        assert KnowledgeWiki.extract_links("No links here.") == []

    def test_extract_links_nested(self) -> None:
        links = KnowledgeWiki.extract_links("Check [[one]], then [[two]].")
        assert "one" in links
        assert "two" in links

    def test_get_linked_pages(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(
            WikiPage(page_id="main", title="Main", content="See [[sub-a]] and [[sub-b]].")
        )
        wiki.add_page(WikiPage(page_id="sub-a", title="Sub A", content="Details A."))
        wiki.add_page(WikiPage(page_id="sub-b", title="Sub B", content="Details B."))

        linked = wiki.get_linked_pages("main")
        linked_ids = [p.page_id for p in linked]
        assert "sub-a" in linked_ids
        assert "sub-b" in linked_ids

    def test_get_linked_pages_missing_target(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="solo", title="Solo", content="Link to [[ghost]]."))
        linked = wiki.get_linked_pages("solo")
        assert linked == []  # ghost doesn't exist

    def test_rebuild_index(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(
            WikiPage(page_id="aaa", title="Alpha Page", content="Content A.", tags=["tag1"])
        )
        wiki.add_page(WikiPage(page_id="bbb", title="Beta Page", content="Content B."))

        index = wiki.rebuild_index()
        assert "Alpha Page" in index
        assert "Beta Page" in index
        assert "tag1" in index

    def test_list_pages_by_type(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="c1", title="C1", content="c", page_type="concept"))
        wiki.add_page(WikiPage(page_id="e1", title="E1", content="e", page_type="entity"))
        wiki.add_page(WikiPage(page_id="c2", title="C2", content="c", page_type="concept"))

        concepts = wiki.list_pages(page_type="concept")
        assert len(concepts) == 2
        entities = wiki.list_pages(page_type="entity")
        assert len(entities) == 1

    def test_lint_detects_orphan_pages(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="hub", title="Hub", content="See [[spoke]]."))
        wiki.add_page(WikiPage(page_id="spoke", title="Spoke", content="Linked from hub."))
        wiki.add_page(WikiPage(page_id="orphan", title="Orphan", content="No one links here."))

        issues = wiki.lint()
        orphan_issues = [i for i in issues if "orphan" in i.lower()]
        orphan_ids = " ".join(orphan_issues)
        assert "orphan" in orphan_ids

    def test_lint_detects_broken_links(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(
            WikiPage(page_id="broken", title="Broken", content="Link to [[nonexistent]].")
        )

        issues = wiki.lint()
        broken = [i for i in issues if "broken_link" in i]
        assert len(broken) >= 1
        assert "nonexistent" in broken[0]

    def test_resolve_links(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="target", title="Target Page", content="Target content."))
        resolved = wiki.resolve_links("See [[target]] for details.")
        assert "Target Page" in resolved
        assert "[[target]]" not in resolved

    def test_resolve_links_unresolved(self) -> None:
        wiki = KnowledgeWiki()
        text = "See [[missing]] here."
        resolved = wiki.resolve_links(text)
        assert "[[missing]]" in resolved  # kept as-is

    def test_update_page(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="upd", title="Upd", content="Old content."))
        wiki.update_page("upd", content="New content with [[link]].", tags=["updated"])
        page = wiki.get_page("upd")
        assert page is not None, f"Expected non-None result for page"
        assert page.content == "New content with [[link]]."
        assert page.tags == ["updated"]
        assert "link" in page.outgoing_links

    def test_save_and_load(self, tmp_path: Path) -> None:
        wiki_dir = str(tmp_path / "wiki")
        wiki = KnowledgeWiki(wiki_dir)
        wiki.add_page(WikiPage(page_id="p1", title="Page 1", content="Content 1.", tags=["t1"]))
        wiki.add_page(WikiPage(page_id="p2", title="Page 2", content="Ref [[p1]]."))
        wiki.save()

        wiki2 = KnowledgeWiki(wiki_dir)
        wiki2.load()
        assert wiki2.get_page("p1") is not None
        assert wiki2.get_page("p2") is not None
        assert wiki2.get_page("p1").title == "Page 1"
        assert wiki2.get_page("p2").outgoing_links == ["p1"]

    def test_to_context_string_respects_budget(self) -> None:
        wiki = KnowledgeWiki()
        wiki.add_page(WikiPage(page_id="long", title="Long Page", content="A" * 5000))
        wiki.add_page(WikiPage(page_id="short", title="Short", content="Brief."))

        # Very small budget: should truncate
        ctx = wiki.to_context_string(["long", "short"], max_tokens=10)
        # Budget is 10*4=40 chars. "## Long Page\nAAAA..." is already over that,
        # so we might get at most one section or empty.
        assert len(ctx) <= 200  # generous upper bound

    def test_to_context_string_missing_pages(self) -> None:
        wiki = KnowledgeWiki()
        assert wiki.to_context_string(["nope"]) == ""

    def test_append_log(self, tmp_path: Path) -> None:
        wiki_dir = str(tmp_path / "wiki_log")
        wiki = KnowledgeWiki(wiki_dir)
        wiki.append_log("test_op", "test details")
        log_path = Path(wiki_dir) / "log.md"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "test_op" in content
        assert "test details" in content


# ======================================================================
# UserKnowledgeStore tests
# ======================================================================


class TestUserProfile:
    def test_creation(self) -> None:
        profile = UserProfile(user_id="u1", role="engineer")
        assert profile.user_id == "u1"
        assert profile.role == "engineer"
        assert profile.expertise == []
        assert profile.preferences == {}

    def test_defaults(self) -> None:
        profile = UserProfile()
        assert profile.user_id == "default"
        assert profile.role == ""


class TestUserKnowledgeStore:
    def test_get_profile_creates_default(self) -> None:
        store = UserKnowledgeStore()
        profile = store.get_profile()
        assert profile.user_id == "default"

    def test_update_profile(self) -> None:
        store = UserKnowledgeStore()
        store.update_profile("default", role="data scientist")
        profile = store.get_profile()
        assert profile.role == "data scientist"
        assert profile.updated_at != ""

    def test_add_preference(self) -> None:
        store = UserKnowledgeStore()
        store.add_preference("output_format", "markdown")
        profile = store.get_profile()
        assert profile.preferences["output_format"] == "markdown"

    def test_add_expertise(self) -> None:
        store = UserKnowledgeStore()
        store.add_expertise("machine learning")
        store.add_expertise("machine learning")  # duplicate
        profile = store.get_profile()
        assert profile.expertise == ["machine learning"]

    def test_add_feedback(self) -> None:
        store = UserKnowledgeStore()
        store.add_feedback("Be more concise")
        store.add_feedback("Good analysis")
        profile = store.get_profile()
        assert len(profile.feedback_history) == 2
        assert "Be more concise" in profile.feedback_history

    def test_record_interaction_pattern(self) -> None:
        store = UserKnowledgeStore()
        store.record_interaction_pattern("prefers bullet points")
        store.record_interaction_pattern("prefers bullet points")  # dup
        profile = store.get_profile()
        assert profile.interaction_patterns == ["prefers bullet points"]

    def test_to_context_string(self) -> None:
        store = UserKnowledgeStore()
        store.update_profile("default", role="analyst")
        store.add_expertise("finance")
        store.add_preference("style", "concise")
        store.add_feedback("Good work")

        ctx = store.to_context_string()
        assert "analyst" in ctx
        assert "finance" in ctx
        assert "concise" in ctx
        assert "Good work" in ctx

    def test_to_context_string_empty(self) -> None:
        store = UserKnowledgeStore()
        ctx = store.to_context_string()
        assert ctx == ""  # empty profile, no fields set

    def test_save_and_load(self, tmp_path: Path) -> None:
        storage = str(tmp_path / "user")
        store = UserKnowledgeStore(storage)
        store.update_profile("default", role="dev")
        store.add_preference("lang", "python")
        store.add_expertise("backend")
        store.add_feedback("nice")
        store.save()

        store2 = UserKnowledgeStore(storage)
        store2.load()
        profile = store2.get_profile()
        assert profile.role == "dev"
        assert profile.preferences["lang"] == "python"
        assert profile.expertise == ["backend"]
        assert "nice" in profile.feedback_history


# ======================================================================
# GraphRenderer tests
# ======================================================================


class TestGraphRenderer:
    def _make_graph(self) -> LongTermMemoryGraph:
        g = LongTermMemoryGraph()
        g.add_node(
            MemoryNode(node_id="n1", content="Revenue Analysis", node_type="fact", tags=["finance"])
        )
        g.add_node(
            MemoryNode(node_id="n2", content="Q4 Growth", node_type="fact", tags=["finance"])
        )
        g.add_node(
            MemoryNode(node_id="n3", content="Cost Concerns", node_type="pattern", tags=["finance"])
        )
        g.add_edge(MemoryEdge(source_id="n1", target_id="n2", relation_type="supports"))
        g.add_edge(MemoryEdge(source_id="n1", target_id="n3", relation_type="contradicts"))
        return g

    def test_to_mermaid_produces_valid_syntax(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        output = renderer.to_mermaid()

        assert "```mermaid" in output
        assert "graph TD" in output
        assert "```" in output
        assert "n1" in output
        assert "supports" in output

    def test_to_mermaid_filter_by_type(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        output = renderer.to_mermaid(node_type="pattern")

        assert "Cost Concerns" in output
        # Should not include fact nodes in node declarations
        lines = output.split("\n")
        node_lines = [line for line in lines if "Revenue Analysis" in line and "[" in line]
        assert len(node_lines) == 0

    def test_to_mermaid_empty_graph(self) -> None:
        g = LongTermMemoryGraph()
        renderer = GraphRenderer(g)
        output = renderer.to_mermaid()
        assert "empty" in output.lower() or "No nodes" in output

    def test_to_mermaid_mindmap(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        output = renderer.to_mermaid_mindmap("n1", depth=2)

        assert "```mermaid" in output
        assert "mindmap" in output
        assert "Revenue Analysis" in output

    def test_to_mermaid_mindmap_missing_root(self) -> None:
        g = LongTermMemoryGraph()
        renderer = GraphRenderer(g)
        output = renderer.to_mermaid_mindmap("missing")
        assert "empty" in output

    def test_to_wiki_pages(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        wiki = KnowledgeWiki()

        count = renderer.to_wiki_pages(wiki)
        assert count == 3
        page = wiki.get_page("n1")
        assert page is not None, f"Expected non-None result for page"
        assert "Revenue Analysis" in page.title
        # Should have wikilinks to neighbors
        assert "[[n2]]" in page.content or "[[n3]]" in page.content

    def test_to_wiki_pages_updates_existing(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        wiki = KnowledgeWiki()

        # Add page first, then render should update
        wiki.add_page(WikiPage(page_id="n1", title="Old Title", content="Old."))
        renderer.to_wiki_pages(wiki)
        page = wiki.get_page("n1")
        assert page is not None, f"Expected non-None result for page"
        assert "Revenue Analysis" in page.content

    def test_to_context_string_with_query(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        ctx = renderer.to_context_string("revenue")
        assert "Revenue Analysis" in ctx

    def test_to_context_string_empty_query(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        assert renderer.to_context_string("") == ""

    def test_to_context_string_no_results(self) -> None:
        g = self._make_graph()
        renderer = GraphRenderer(g)
        assert renderer.to_context_string("zzzzzzz") == ""

    def test_sanitize_mermaid_id(self) -> None:
        assert GraphRenderer._sanitize_mermaid_id("hello-world") == "hello_world"
        assert GraphRenderer._sanitize_mermaid_id("a.b/c") == "a_b_c"
        assert GraphRenderer._sanitize_mermaid_id("simple") == "simple"
        assert GraphRenderer._sanitize_mermaid_id("has spaces") == "has_spaces"

    def test_sanitize_mermaid_label(self) -> None:
        assert "[" not in GraphRenderer._sanitize_mermaid_label("test[1]")
        assert "]" not in GraphRenderer._sanitize_mermaid_label("test[1]")
        assert "|" not in GraphRenderer._sanitize_mermaid_label("a|b")
        assert '"' not in GraphRenderer._sanitize_mermaid_label('say "hi"')


# ======================================================================
# KnowledgeManager tests
# ======================================================================


class TestKnowledgeManager:
    def _make_km(self, tmp_path) -> KnowledgeManager:
        """Helper: construct a fully-injected KnowledgeManager for tests."""
        graph = LongTermMemoryGraph(str(tmp_path / "graph.json"))
        return KnowledgeManager(
            wiki=KnowledgeWiki(str(tmp_path / "wiki")),
            user_store=UserKnowledgeStore(str(tmp_path / "user")),
            graph=graph,
            renderer=GraphRenderer(graph),
        )

    def test_ingest_text_creates_wiki_page(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        page_id = km.ingest_text("Test Finding", "This is a test finding.", tags=["test"])
        assert page_id != ""
        page = km.wiki.get_page(page_id)
        assert page is not None, f"Expected non-None result for page"
        assert page.title == "Test Finding"
        assert "test" in page.tags

    def test_ingest_text_slug(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        page_id = km.ingest_text("Hello World Example", "Content here.")
        assert page_id == "hello-world-example"

    def test_ingest_structured_creates_graph_nodes(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        facts = [
            {"content": "Python is popular", "type": "fact", "tags": ["language"]},
            {"content": "TDD improves quality", "type": "method", "tags": ["practice"]},
        ]
        count = km.ingest_structured(facts)
        assert count == 2
        assert km.graph.node_count() == 2

    def test_ingest_structured_skips_empty(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        facts = [{"content": "", "type": "fact"}]
        count = km.ingest_structured(facts)
        assert count == 0

    def test_query_searches_across_sources(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        km.ingest_text("Revenue Report", "Revenue grew 20% in Q4.")
        km.ingest_structured(
            [{"content": "Revenue trend is positive", "type": "fact", "tags": ["finance"]}]
        )
        km.user_store.update_profile("default", role="analyst")

        result = km.query("revenue")
        assert result.total_results >= 2
        assert len(result.wiki_pages) >= 1
        assert len(result.graph_nodes) >= 1
        assert "analyst" in result.user_context

    def test_query_empty(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        result = km.query("")
        assert result.total_results == 0

    def test_query_for_context_respects_budget(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        km.ingest_text("Long Doc", "A" * 10000)
        ctx = km.query_for_context("long", budget_tokens=50)
        # Budget is 50*4=200 chars
        assert len(ctx) < 500  # generous upper bound

    def test_get_stats(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        km.ingest_text("Page A", "Content A.")
        km.ingest_text("Page B", "Content B.")
        km.ingest_structured([{"content": "Fact X", "type": "fact"}])
        km.user_store.add_preference("k", "v")
        km.user_store.add_expertise("ML")

        stats = km.get_stats()
        assert stats["wiki_pages"] == 2
        assert stats["graph_nodes"] == 1
        assert stats["graph_edges"] == 0
        assert stats["user_preferences"] == 1
        assert stats["user_expertise_areas"] == 1

    def test_lint(self, tmp_path) -> None:
        km = self._make_km(tmp_path)
        km.wiki.add_page(
            WikiPage(page_id="broken", title="Broken", content="Link to [[nonexistent]].")
        )
        issues = km.lint()
        assert any("broken_link" in i for i in issues)

    def test_ingest_from_session(self, tmp_path) -> None:
        @dataclass
        class FakeSession:
            findings: list[str] = field(default_factory=list)
            user_feedback: list[str] = field(default_factory=list)
            facts: list[dict] = field(default_factory=list)

        session = FakeSession(
            findings=["Key finding: revenue is up"],
            user_feedback=["Be more concise"],
            facts=[{"content": "Revenue up 20%", "type": "fact"}],
        )
        km = self._make_km(tmp_path)
        count = km.ingest_from_session(session)
        assert count == 3  # 1 finding + 1 feedback + 1 fact
        assert len(km.wiki.list_pages()) == 1
        assert km.graph.node_count() == 1


class TestKnowledgeResult:
    def test_to_context_string(self) -> None:
        result = KnowledgeResult(
            wiki_pages=[WikiPage(page_id="p", title="Page", content="Page content.")],
            graph_nodes=[MemoryNode(node_id="n", content="A fact", node_type="fact")],
            user_context="Role: analyst",
            total_results=2,
        )
        ctx = result.to_context_string()
        assert "analyst" in ctx
        assert "Page" in ctx
        assert "A fact" in ctx

    def test_to_context_string_empty(self) -> None:
        result = KnowledgeResult()
        ctx = result.to_context_string()
        assert ctx == ""

    def test_to_context_string_budget(self) -> None:
        result = KnowledgeResult(
            wiki_pages=[WikiPage(page_id="big", title="Big", content="X" * 10000)],
            total_results=1,
        )
        ctx = result.to_context_string(max_tokens=20)
        # Budget 20*4=80 chars. Should not include the huge page.
        assert len(ctx) < 300

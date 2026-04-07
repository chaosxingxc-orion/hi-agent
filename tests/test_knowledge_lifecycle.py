"""Tests for knowledge API endpoints, SystemBuilder wiring, and full lifecycle."""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from hi_agent.knowledge.knowledge_manager import KnowledgeManager
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode
from hi_agent.server.app import AgentServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wiki(tmp_path):
    return KnowledgeWiki(str(tmp_path / "wiki"))


@pytest.fixture()
def user_store(tmp_path):
    return UserKnowledgeStore(str(tmp_path / "user"))


@pytest.fixture()
def graph(tmp_path):
    return LongTermMemoryGraph(str(tmp_path / "graph.json"))


@pytest.fixture()
def renderer(graph):
    return GraphRenderer(graph)


@pytest.fixture()
def km(wiki, user_store, graph, renderer):
    return KnowledgeManager(
        wiki=wiki, user_store=user_store, graph=graph, renderer=renderer,
    )


def _make_test_server(km: KnowledgeManager) -> AgentServer:
    """Create a server on a random port with knowledge_manager wired."""
    server = AgentServer(host="127.0.0.1", port=0)
    server.knowledge_manager = km
    return server


def _request(
    server: AgentServer,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Issue a request to the test server and return (status, json_body)."""
    import http.client

    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    headers = {"Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    return resp.status, json.loads(raw) if raw else {}


@pytest.fixture()
def live_server(km):
    """Fixture that starts a server with knowledge_manager in a thread."""
    server = _make_test_server(km)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


# ---------------------------------------------------------------------------
# Part 1: API endpoint tests
# ---------------------------------------------------------------------------


class TestKnowledgeIngest:
    """Test POST /knowledge/ingest."""

    def test_ingest_creates_wiki_page(self, live_server: AgentServer) -> None:
        """Ingesting text creates a wiki page and returns 201."""
        status, body = _request(live_server, "POST", "/knowledge/ingest", {
            "title": "Revenue Analysis",
            "content": "Q4 revenue grew 15% year-over-year.",
            "tags": ["finance", "q4"],
        })
        assert status == 201
        assert body["status"] == "created"
        assert body["page_id"]

    def test_ingest_missing_fields_returns_400(self, live_server: AgentServer) -> None:
        """Missing title or content returns 400."""
        status, body = _request(live_server, "POST", "/knowledge/ingest", {
            "title": "Only title",
        })
        assert status == 400

    def test_ingest_no_knowledge_manager_returns_503(self) -> None:
        """Server without knowledge_manager returns 503."""
        server = AgentServer(host="127.0.0.1", port=0)
        # knowledge_manager is None by default
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _request(server, "POST", "/knowledge/ingest", {
                "title": "t", "content": "c",
            })
            assert status == 503
            assert body["error"] == "knowledge_not_configured"
        finally:
            server.shutdown()


class TestKnowledgeIngestStructured:
    """Test POST /knowledge/ingest-structured."""

    def test_ingest_structured_creates_graph_nodes(
        self, live_server: AgentServer, graph: LongTermMemoryGraph,
    ) -> None:
        """Ingesting structured facts creates graph nodes."""
        status, body = _request(live_server, "POST", "/knowledge/ingest-structured", {
            "facts": [
                {"content": "Python is a programming language", "type": "fact", "tags": ["tech"]},
                {"content": "Flask is a web framework", "type": "fact", "tags": ["tech"]},
            ],
        })
        assert status == 201
        assert body["nodes_created"] == 2
        assert body["status"] == "created"
        assert graph.node_count() == 2


class TestKnowledgeQuery:
    """Test GET /knowledge/query."""

    def test_query_returns_results(
        self, live_server: AgentServer, km: KnowledgeManager,
    ) -> None:
        """Query returns results after ingesting content."""
        km.ingest_text("Revenue Report", "Q4 revenue was strong.", ["finance"])
        status, body = _request(
            live_server, "GET", "/knowledge/query?q=revenue&limit=5&budget=1000",
        )
        assert status == 200
        assert body["query"] == "revenue"
        assert body["total_results"] >= 1
        assert "context" in body

    def test_query_missing_q_returns_400(self, live_server: AgentServer) -> None:
        """Query without q param returns 400."""
        status, body = _request(live_server, "GET", "/knowledge/query")
        assert status == 400
        assert body["error"] == "missing_query_param_q"


class TestKnowledgeStatus:
    """Test GET /knowledge/status."""

    def test_status_returns_counts(
        self, live_server: AgentServer, km: KnowledgeManager,
    ) -> None:
        """Status returns wiki_pages, graph_nodes, etc."""
        km.ingest_text("Test Page", "Some content", ["test"])
        status, body = _request(live_server, "GET", "/knowledge/status")
        assert status == 200
        assert body["wiki_pages"] >= 1
        assert "graph_nodes" in body
        assert "graph_edges" in body
        assert "user_preferences" in body
        assert "user_expertise_areas" in body


class TestKnowledgeLint:
    """Test POST /knowledge/lint."""

    def test_lint_returns_issues_list(self, live_server: AgentServer) -> None:
        """Lint returns a list of issues (possibly empty)."""
        status, body = _request(live_server, "POST", "/knowledge/lint")
        assert status == 200
        assert "issues" in body
        assert isinstance(body["issues"], list)
        assert "count" in body


class TestKnowledgeSync:
    """Test POST /knowledge/sync."""

    def test_sync_transfers_graph_to_wiki(
        self, live_server: AgentServer, graph: LongTermMemoryGraph,
        wiki: KnowledgeWiki,
    ) -> None:
        """Sync creates wiki pages from graph nodes."""
        # Add nodes to graph directly
        graph.add_node(MemoryNode(
            node_id="node-a", content="Alpha concept", node_type="fact", tags=["a"],
        ))
        graph.add_node(MemoryNode(
            node_id="node-b", content="Beta concept", node_type="fact", tags=["b"],
        ))
        status, body = _request(live_server, "POST", "/knowledge/sync")
        assert status == 200
        assert body["pages_synced"] == 2
        assert body["status"] == "completed"
        # Wiki should now contain the pages
        assert wiki.get_page("node-a") is not None
        assert wiki.get_page("node-b") is not None


# ---------------------------------------------------------------------------
# Part 2: SystemBuilder tests
# ---------------------------------------------------------------------------


class TestSystemBuilderKnowledge:
    """Test SystemBuilder.build_knowledge_manager and related wiring."""

    def test_build_knowledge_manager_creates_working_instance(
        self, tmp_path,
    ) -> None:
        """build_knowledge_manager returns a functional KnowledgeManager."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = SystemBuilder(config)
        km = builder.build_knowledge_manager()

        assert km is not None
        assert km.wiki is not None
        assert km.user_store is not None
        assert km.graph is not None
        assert km.renderer is not None

        # Functional: ingest and query
        page_id = km.ingest_text("Builder Test", "Works correctly", ["test"])
        assert page_id
        result = km.query("Builder")
        assert result.total_results >= 1

    def test_build_executor_includes_knowledge_query_fn(
        self, tmp_path,
    ) -> None:
        """build_executor wires knowledge_query_fn from knowledge_manager."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.contracts import TaskContract

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = SystemBuilder(config)
        contract = TaskContract(
            task_id="test-123", goal="test goal",
            task_family="quick_task", risk_level="low",
        )
        executor = builder.build_executor(contract)
        assert executor.knowledge_query_fn is not None

    def test_build_server_sets_knowledge_manager(self, tmp_path) -> None:
        """build_server creates a server with knowledge_manager set."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig(
            episodic_storage_dir=str(tmp_path / "episodes"),
            server_host="127.0.0.1",
            server_port=0,
        )
        builder = SystemBuilder(config)
        server = builder.build_server()
        assert server.knowledge_manager is not None
        server.server_close()


# ---------------------------------------------------------------------------
# Part 3: Full lifecycle test
# ---------------------------------------------------------------------------


class TestKnowledgeFullLifecycle:
    """End-to-end: ingest text -> query -> ingest structured -> query -> sync -> verify."""

    def test_full_lifecycle(
        self, live_server: AgentServer, km: KnowledgeManager,
        graph: LongTermMemoryGraph, wiki: KnowledgeWiki,
    ) -> None:
        """Full lifecycle: ingest, query, structured ingest, sync, verify."""
        # Step 1: Ingest text knowledge
        status, body = _request(live_server, "POST", "/knowledge/ingest", {
            "title": "Machine Learning Basics",
            "content": "ML is a subset of AI that learns from data.",
            "tags": ["ml", "ai"],
        })
        assert status == 201
        text_page_id = body["page_id"]

        # Step 2: Query finds the text knowledge
        status, body = _request(
            live_server, "GET", "/knowledge/query?q=machine+learning&limit=5",
        )
        assert status == 200
        assert body["total_results"] >= 1
        assert "ML" in body["context"] or "machine" in body["context"].lower()

        # Step 3: Ingest structured facts
        status, body = _request(live_server, "POST", "/knowledge/ingest-structured", {
            "facts": [
                {"content": "Neural networks are a key ML technique", "type": "fact", "tags": ["ml"]},
                {"content": "Deep learning uses multiple layers", "type": "method", "tags": ["ml", "dl"]},
            ],
        })
        assert status == 201
        assert body["nodes_created"] == 2

        # Step 4: Query finds both text and structured knowledge
        status, body = _request(
            live_server, "GET", "/knowledge/query?q=ML+technique&limit=10",
        )
        assert status == 200
        assert body["total_results"] >= 1

        # Step 5: Sync graph -> wiki
        status, body = _request(live_server, "POST", "/knowledge/sync")
        assert status == 200
        assert body["pages_synced"] >= 2

        # Step 6: Verify wiki has graph content
        # The text page should still exist
        assert wiki.get_page(text_page_id) is not None
        # Graph nodes should now be in wiki too
        all_pages = wiki.list_pages()
        assert len(all_pages) >= 3  # 1 text + 2 synced from graph

        # Step 7: Status reflects everything
        status, body = _request(live_server, "GET", "/knowledge/status")
        assert status == 200
        assert body["wiki_pages"] >= 3
        assert body["graph_nodes"] >= 2

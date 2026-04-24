"""Tests for MemoryLifecycleManager, API endpoints, and SystemBuilder wiring."""

from __future__ import annotations

import json
import threading
from io import BytesIO

import pytest
from hi_agent.memory.long_term import LongTermMemoryGraph
from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore
from hi_agent.memory.short_term import ShortTermMemory, ShortTermMemoryStore
from hi_agent.server.dream_scheduler import MemoryLifecycleManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def short_store(tmp_path):
    return ShortTermMemoryStore(str(tmp_path / "short_term"))


@pytest.fixture()
def mid_store(tmp_path):
    return MidTermMemoryStore(str(tmp_path / "mid_term"))


@pytest.fixture()
def graph(tmp_path):
    return LongTermMemoryGraph(str(tmp_path / "long_term" / "graph.json"))


@pytest.fixture()
def populated_short_store(short_store):
    """Short-term store with two sessions for 2026-04-07."""
    for i in range(2):
        mem = ShortTermMemory(
            session_id=f"sess_{i}",
            run_id=f"run_{i}",
            task_goal=f"Task {i}",
            stages_completed=["S1_understand", "S2_gather"],
            key_findings=[f"finding_{i}"],
            key_decisions=[f"decision_{i}"],
            tools_used=["web_search"],
            errors_encountered=[],
            outcome="completed",
            created_at="2026-04-07T10:00:00+00:00",
        )
        short_store.save(mem)
    return short_store


@pytest.fixture()
def populated_mid_store(mid_store):
    """Mid-term store with a daily summary."""
    summary = DailySummary(
        date="2026-04-07",
        sessions_count=2,
        tasks_completed=["Task 0", "Task 1"],
        key_learnings=["learning A"],
        patterns_observed=["pattern X"],
        skills_used=["web_search"],
    )
    mid_store.save(summary)
    return mid_store


@pytest.fixture()
def manager_all(populated_short_store, populated_mid_store, graph):
    return MemoryLifecycleManager(
        short_term_store=populated_short_store,
        mid_term_store=populated_mid_store,
        long_term_graph=graph,
    )


# ---------------------------------------------------------------------------
# MemoryLifecycleManager unit tests
# ---------------------------------------------------------------------------


class TestTriggerDream:
    def test_dream_with_populated_store(self, manager_all):
        result = manager_all.trigger_dream("2026-04-07")
        assert result["status"] == "completed"
        assert result["date"] == "2026-04-07"
        assert result["sessions_count"] == 2
        assert isinstance(result["tasks_completed"], int)
        assert isinstance(result["key_learnings"], int)

    def test_dream_no_stores_returns_skipped(self):
        mgr = MemoryLifecycleManager()
        result = mgr.trigger_dream()
        assert result["status"] == "skipped"
        assert result["reason"] == "stores_not_configured"


class TestTriggerConsolidation:
    def test_consolidation_with_populated_store(
        self, populated_short_store, populated_mid_store, graph, tmp_path
    ):
        mgr = MemoryLifecycleManager(
            short_term_store=populated_short_store,
            mid_term_store=populated_mid_store,
            long_term_graph=graph,
        )
        result = mgr.trigger_consolidation(days=7)
        assert result["status"] == "completed"
        assert result["nodes_affected"] >= 0
        assert "total_nodes" in result
        assert "total_edges" in result

    def test_consolidation_no_stores_returns_skipped(self):
        mgr = MemoryLifecycleManager()
        result = mgr.trigger_consolidation()
        assert result["status"] == "skipped"


class TestTriggerFullCycle:
    def test_full_cycle_runs_both(self, manager_all):
        result = manager_all.trigger_full_cycle("2026-04-07", days=7)
        assert "dream" in result
        assert "consolidation" in result
        assert result["dream"]["status"] == "completed"
        assert result["consolidation"]["status"] == "completed"


class TestGetStatus:
    def test_status_returns_tier_counts(self, manager_all):
        status = manager_all.get_status()
        assert "short_term" in status
        assert "mid_term" in status
        assert "long_term" in status
        # Short-term has 2 items
        assert status["short_term"]["count"] == 2
        # Mid-term has 1 daily summary
        assert status["mid_term"]["count"] == 1
        # Long-term is empty initially
        assert status["long_term"]["nodes"] == 0

    def test_status_with_no_stores(self):
        mgr = MemoryLifecycleManager()
        status = mgr.get_status()
        assert status["short_term"] is None
        assert status["mid_term"] is None
        assert status["long_term"] is None


class TestThreadSafety:
    def test_concurrent_dream_calls(self, manager_all):
        """Concurrent trigger_dream calls should not crash."""
        errors: list[Exception] = []

        def dream_call():
            try:
                manager_all.trigger_dream("2026-04-07")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=dream_call) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert errors == [], f"Concurrent dream calls raised: {errors}"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class _FakeSocket:
    """Minimal socket-like object for handler tests."""

    def __init__(self, request_bytes: bytes) -> None:
        self._input = BytesIO(request_bytes)
        self._output = BytesIO()

    def makefile(self, mode: str, buffering: int = -1) -> BytesIO:
        if "r" in mode:
            return self._input
        return self._output


def _build_request(method: str, path: str, body: dict | None = None) -> bytes:
    body_bytes = json.dumps(body).encode() if body else b""
    lines = [
        f"{method} {path} HTTP/1.1",
        "Host: localhost",
        f"Content-Length: {len(body_bytes)}",
        "Content-Type: application/json",
        "",
        "",
    ]
    return ("\r\n".join(lines)).encode() + body_bytes


def _make_handler(server, request_bytes: bytes):
    """Construct an AgentAPIHandler from raw request bytes."""
    from hi_agent.server.app import AgentAPIHandler

    sock = _FakeSocket(request_bytes)
    handler = AgentAPIHandler.__new__(AgentAPIHandler)
    handler.request = sock
    handler.client_address = ("127.0.0.1", 9999)
    handler.server = server
    handler.rfile = sock.makefile("rb")
    handler.wfile = sock.makefile("wb")
    handler.requestline = ""
    handler.command = ""
    handler.request_version = "HTTP/1.1"
    handler.close_connection = True
    # Parse the request line and headers
    raw_line = handler.rfile.readline(65537).decode("iso-8859-1").rstrip("\r\n")
    handler.requestline = raw_line
    words = raw_line.split()
    handler.command = words[0]
    handler.path = words[1]
    handler.request_version = words[2]
    # Parse headers
    import http.client

    handler.headers = http.client.parse_headers(handler.rfile)
    return handler


class TestAPIEndpoints:
    @pytest.fixture()
    def test_server(self, manager_all):
        """AgentServer with memory_manager wired, returning TestClient."""
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=9999)
        server.memory_manager = manager_all
        return TestClient(server.app)

    def test_post_memory_dream(self, test_server):
        resp = test_server.post("/memory/dream", json={"date": "2026-04-07"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_post_memory_consolidate(self, test_server):
        resp = test_server.post("/memory/consolidate", json={"days": 7})
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_get_memory_status(self, test_server):
        resp = test_server.get("/memory/status")
        assert resp.status_code == 200
        result = resp.json()
        assert "short_term" in result
        assert "mid_term" in result
        assert "long_term" in result

    def test_memory_not_configured(self):
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=9999)
        server.memory_manager = None
        client = TestClient(server.app)
        resp = client.get("/memory/status")
        result = resp.json()
        assert result["error"] == "memory_not_configured"


# ---------------------------------------------------------------------------
# SystemBuilder integration test
# ---------------------------------------------------------------------------


class TestSystemBuilder:
    def test_builds_all_memory_stores(self, tmp_path):
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = SystemBuilder(config)

        _pid = "memory-transfer-test"
        short = builder.build_short_term_store(profile_id=_pid, workspace_key=None)
        mid = builder.build_mid_term_store(profile_id=_pid, workspace_key=None)
        graph = builder.build_long_term_graph(profile_id=_pid, workspace_key=None)
        retrieval = builder.build_retrieval_engine(profile_id=_pid)
        mgr = builder.build_memory_lifecycle_manager(profile_id=_pid)

        assert short is not None
        assert mid is not None
        assert graph is not None
        assert retrieval is not None
        assert mgr is not None
        assert mgr._dream is not None
        assert mgr._consolidator is not None


# ---------------------------------------------------------------------------
# Full lifecycle integration test
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_stm_to_dream_to_consolidation(self, tmp_path):
        """Create STMs -> dream -> DailySummary exists -> consolidate -> graph nodes."""
        short = ShortTermMemoryStore(str(tmp_path / "short"))
        mid = MidTermMemoryStore(str(tmp_path / "mid"))
        graph = LongTermMemoryGraph(str(tmp_path / "lt" / "graph.json"))

        # Step 1: Create short-term memories
        for i in range(3):
            mem = ShortTermMemory(
                session_id=f"lifecycle_{i}",
                run_id=f"run_{i}",
                task_goal=f"Lifecycle task {i}",
                stages_completed=["S1_understand"],
                key_findings=[f"finding {i}"],
                outcome="completed",
                created_at="2026-04-07T12:00:00+00:00",
            )
            short.save(mem)

        mgr = MemoryLifecycleManager(
            short_term_store=short,
            mid_term_store=mid,
            long_term_graph=graph,
        )

        # Step 2: Dream
        dream_result = mgr.trigger_dream("2026-04-07")
        assert dream_result["status"] == "completed"
        assert dream_result["sessions_count"] == 3

        # Verify DailySummary was created
        summary = mid.load("2026-04-07")
        assert summary is not None
        assert summary.sessions_count == 3
        assert len(summary.tasks_completed) == 3

        # Step 3: Consolidate
        consol_result = mgr.trigger_consolidation(days=7)
        assert consol_result["status"] == "completed"
        assert consol_result["nodes_affected"] > 0
        assert consol_result["total_nodes"] > 0

        # Verify graph nodes exist
        assert graph.node_count() > 0

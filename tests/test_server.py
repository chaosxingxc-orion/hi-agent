"""Tests for the hi-agent entry layer: RunManager, AgentAPIHandler, and CLI."""

from __future__ import annotations

import io
import json
import threading
import time
from http.server import HTTPServer
from typing import Any
from unittest.mock import patch

import pytest

from hi_agent.server.app import AgentAPIHandler, AgentServer
from hi_agent.server.run_manager import ManagedRun, RunManager


# ---------------------------------------------------------------------------
# RunManager tests
# ---------------------------------------------------------------------------


class TestRunManagerCreate:
    """Test run creation logic."""

    def test_create_returns_run_id(self) -> None:
        """Creating a run returns a non-empty run_id."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})
        assert run_id
        assert isinstance(run_id, str)

    def test_create_uses_task_id_if_present(self) -> None:
        """If task_id is in the contract, it is used as run_id."""
        mgr = RunManager()
        run_id = mgr.create_run({"task_id": "my-task-42", "goal": "test"})
        assert run_id == "my-task-42"

    def test_create_sets_initial_state(self) -> None:
        """New runs start in 'created' state."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})
        run = mgr.get_run(run_id)
        assert run is not None
        assert run.state == "created"
        assert run.created_at != ""
        assert run.updated_at != ""


class TestRunManagerStartAndQuery:
    """Test run execution and querying."""

    def test_start_run_executes(self) -> None:
        """Starting a run transitions through running to completed."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})

        def executor(run: ManagedRun) -> str:
            return "done"

        mgr.start_run(run_id, executor)
        # Wait for thread to finish.
        run = mgr.get_run(run_id)
        assert run is not None
        assert run.thread is not None
        run.thread.join(timeout=5)
        assert run.state == "completed"
        assert run.result == "done"

    def test_start_run_captures_error(self) -> None:
        """Executor exceptions transition the run to failed state."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})

        def bad_executor(run: ManagedRun) -> None:
            raise RuntimeError("boom")

        mgr.start_run(run_id, bad_executor)
        run = mgr.get_run(run_id)
        assert run is not None
        assert run.thread is not None
        run.thread.join(timeout=5)
        assert run.state == "failed"
        assert run.error == "boom"

    def test_get_nonexistent_returns_none(self) -> None:
        """Getting a missing run returns None."""
        mgr = RunManager()
        assert mgr.get_run("nope") is None


class TestRunManagerList:
    """Test listing runs."""

    def test_list_returns_all(self) -> None:
        """List should return all created runs."""
        mgr = RunManager()
        mgr.create_run({"task_id": "a", "goal": "one"})
        mgr.create_run({"task_id": "b", "goal": "two"})
        runs = mgr.list_runs()
        assert len(runs) == 2
        ids = {r.run_id for r in runs}
        assert ids == {"a", "b"}


class TestRunManagerCancel:
    """Test run cancellation."""

    def test_cancel_created_run(self) -> None:
        """Cancelling a created run sets state to cancelled."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})
        assert mgr.cancel_run(run_id) is True
        run = mgr.get_run(run_id)
        assert run is not None
        assert run.state == "cancelled"

    def test_cancel_completed_run_fails(self) -> None:
        """Cancelling a completed run returns False."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})
        mgr.start_run(run_id, lambda r: "ok")
        run = mgr.get_run(run_id)
        assert run is not None and run.thread is not None
        run.thread.join(timeout=5)
        assert mgr.cancel_run(run_id) is False

    def test_cancel_nonexistent_run(self) -> None:
        """Cancelling a non-existent run returns False."""
        mgr = RunManager()
        assert mgr.cancel_run("nope") is False


class TestRunManagerThreadSafety:
    """Test concurrent access to RunManager."""

    def test_concurrent_creates(self) -> None:
        """Multiple threads creating runs concurrently should not lose any."""
        mgr = RunManager()
        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[str] = []

        def create_one(idx: int) -> None:
            barrier.wait()
            try:
                mgr.create_run({"task_id": f"t-{idx}", "goal": f"goal-{idx}"})
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=create_one, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        assert len(mgr.list_runs()) == n_threads


class TestRunManagerMaxConcurrent:
    """Test max_concurrent enforcement."""

    def test_semaphore_limits_concurrent(self) -> None:
        """Only max_concurrent runs should execute simultaneously."""
        mgr = RunManager(max_concurrent=2)
        active = threading.Semaphore(0)
        peak_lock = threading.Lock()
        peak = [0]
        current = [0]

        def slow_executor(run: ManagedRun) -> str:
            with peak_lock:
                current[0] += 1
                if current[0] > peak[0]:
                    peak[0] = current[0]
            time.sleep(0.1)
            with peak_lock:
                current[0] -= 1
            active.release()
            return "done"

        ids = []
        for i in range(4):
            rid = mgr.create_run({"task_id": f"r-{i}", "goal": "test"})
            ids.append(rid)
            mgr.start_run(rid, slow_executor)

        # Wait for all to finish (some may fail due to semaphore).
        for rid in ids:
            run = mgr.get_run(rid)
            if run and run.thread:
                run.thread.join(timeout=10)

        # The peak concurrent should be at most 2.
        assert peak[0] <= 2


class TestRunManagerSerialize:
    """Test serialization."""

    def test_to_dict(self) -> None:
        """to_dict produces a JSON-safe dictionary."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"})
        run = mgr.get_run(run_id)
        assert run is not None
        d = mgr.to_dict(run)
        assert d["run_id"] == run_id
        assert d["state"] == "created"
        assert "thread" not in d
        # Should be JSON-serializable.
        json.dumps(d)


# ---------------------------------------------------------------------------
# HTTP API tests (using a real server on a random port)
# ---------------------------------------------------------------------------


def _make_test_server() -> AgentServer:
    """Create a server on a random port for testing."""
    server = AgentServer(host="127.0.0.1", port=0)
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
def live_server():
    """Fixture that starts a server in a thread and yields it."""
    server = _make_test_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


class TestHealthEndpoint:
    """Test GET /health."""

    def test_health_returns_ok(self, live_server: AgentServer) -> None:
        """Health check returns 200 with status ok."""
        status, body = _request(live_server, "GET", "/health")
        assert status == 200
        assert body["status"] == "ok"


class TestManifestEndpoint:
    """Test GET /manifest."""

    def test_manifest_returns_info(self, live_server: AgentServer) -> None:
        """Manifest returns system metadata."""
        status, body = _request(live_server, "GET", "/manifest")
        assert status == 200
        assert body["name"] == "hi-agent"
        assert body["framework"] == "TRACE"
        assert "stages" in body
        assert "endpoints" in body


class TestRunsEndpoints:
    """Test run CRUD endpoints."""

    def test_create_and_get_run(self, live_server: AgentServer) -> None:
        """POST /runs creates a run, GET /runs/{id} retrieves it."""
        status, body = _request(
            live_server, "POST", "/runs", {"task_id": "abc", "goal": "test goal"}
        )
        assert status == 201
        assert body["run_id"] == "abc"
        assert body["state"] == "created"

        status2, body2 = _request(live_server, "GET", "/runs/abc")
        assert status2 == 200
        assert body2["run_id"] == "abc"

    def test_create_without_goal_fails(self, live_server: AgentServer) -> None:
        """POST /runs without goal returns 400."""
        status, body = _request(live_server, "POST", "/runs", {"task_id": "x"})
        assert status == 400
        assert body["error"] == "missing_goal"

    def test_list_runs(self, live_server: AgentServer) -> None:
        """GET /runs lists created runs."""
        _request(live_server, "POST", "/runs", {"task_id": "r1", "goal": "a"})
        _request(live_server, "POST", "/runs", {"task_id": "r2", "goal": "b"})
        status, body = _request(live_server, "GET", "/runs")
        assert status == 200
        ids = {r["run_id"] for r in body["runs"]}
        assert "r1" in ids
        assert "r2" in ids

    def test_get_nonexistent_run(self, live_server: AgentServer) -> None:
        """GET /runs/missing returns 404."""
        status, body = _request(live_server, "GET", "/runs/missing")
        assert status == 404

    def test_signal_cancel(self, live_server: AgentServer) -> None:
        """POST /runs/{id}/signal with cancel signal works."""
        _request(live_server, "POST", "/runs", {"task_id": "s1", "goal": "test"})
        status, body = _request(
            live_server, "POST", "/runs/s1/signal", {"signal": "cancel"}
        )
        assert status == 200
        assert body["state"] == "cancelled"

    def test_signal_unknown(self, live_server: AgentServer) -> None:
        """POST /runs/{id}/signal with unknown signal returns 400."""
        _request(live_server, "POST", "/runs", {"task_id": "s2", "goal": "test"})
        status, body = _request(
            live_server, "POST", "/runs/s2/signal", {"signal": "explode"}
        )
        assert status == 400
        assert body["error"] == "unknown_signal"

    def test_not_found_routes(self, live_server: AgentServer) -> None:
        """Unknown paths return 404."""
        status, _ = _request(live_server, "GET", "/nope")
        assert status == 404
        status2, _ = _request(live_server, "POST", "/nope")
        assert status2 == 404


# ---------------------------------------------------------------------------
# CLI argument parsing tests
# ---------------------------------------------------------------------------


class TestCLIParsing:
    """Test CLI argument parsing without starting a server."""

    def test_serve_defaults(self) -> None:
        """Serve command parses with defaults."""
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "0.0.0.0"
        assert args.port == 8080

    def test_serve_custom(self) -> None:
        """Serve command accepts custom host and port."""
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["serve", "--host", "localhost", "--port", "9090"])
        assert args.host == "localhost"
        assert args.port == 9090

    def test_run_command(self) -> None:
        """Run command parses goal and options."""
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "run",
            "--goal",
            "summarize this",
            "--task-family",
            "analysis",
            "--risk-level",
            "medium",
            "--json",
        ])
        assert args.command == "run"
        assert args.goal == "summarize this"
        assert args.task_family == "analysis"
        assert args.risk_level == "medium"
        assert args.json is True

    def test_status_with_run_id(self) -> None:
        """Status command parses optional run-id."""
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["status", "--run-id", "abc-123"])
        assert args.command == "status"
        assert args.run_id == "abc-123"

    def test_status_without_run_id(self) -> None:
        """Status command works without run-id."""
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"
        assert args.run_id is None

    def test_health_command(self) -> None:
        """Health command is recognized."""
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["health"])
        assert args.command == "health"

    def test_no_command_exits(self) -> None:
        """No command provided causes SystemExit."""
        from hi_agent.cli import main

        with patch("sys.argv", ["hi_agent"]):
            with pytest.raises(SystemExit):
                main()

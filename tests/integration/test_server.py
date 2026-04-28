"""Tests for the hi-agent entry layer: RunManager, AgentAPIHandler, and CLI."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import patch

import pytest
from hi_agent.server.app import AgentServer
from hi_agent.server.run_manager import ManagedRun, RunManager
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# RunManager tests
# ---------------------------------------------------------------------------


class TestRunManagerCreate:
    """Test run creation logic."""

    def test_create_returns_run_id(self) -> None:
        """Creating a run returns a ManagedRun with a non-empty run_id."""
        mgr = RunManager()
        managed = mgr.create_run({"goal": "test"})
        run_id = managed.run_id
        assert run_id
        assert isinstance(run_id, str)

    def test_create_generates_uuid4_run_id(self) -> None:
        """create_run always generates a UUID4 run_id regardless of task_id."""
        import uuid

        mgr = RunManager()
        run_id = mgr.create_run({"task_id": "my-task-42", "goal": "test"}).run_id
        parsed = uuid.UUID(run_id, version=4)
        assert str(parsed) == run_id

    def test_create_sets_initial_state(self) -> None:
        """New runs start in 'created' state."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"}).run_id
        run = mgr.get_run(run_id)
        assert run is not None, "Expected non-None result for run"
        assert run.state == "created"
        assert run.created_at != ""
        assert run.updated_at != ""


class TestRunManagerStartAndQuery:
    """Test run execution and querying."""

    def test_start_run_executes(self) -> None:
        """Starting a run transitions through running to completed."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"}).run_id

        def executor(run: ManagedRun) -> str:
            return "done"

        mgr.start_run(run_id, executor)
        # Wait for the background worker to pick up and finish.
        run = mgr.get_run(run_id)
        assert run is not None, "Expected non-None result for run"
        deadline = time.monotonic() + 5
        while run.thread is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert run.thread is not None
        run.thread.join(timeout=5)
        assert run.state == "completed"
        assert run.result == "done"

    def test_start_run_captures_error(self) -> None:
        """Executor exceptions transition the run to failed state."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"}).run_id

        def bad_executor(run: ManagedRun) -> None:
            raise RuntimeError("boom")

        mgr.start_run(run_id, bad_executor)
        run = mgr.get_run(run_id)
        assert run is not None, "Expected non-None result for run"
        deadline = time.monotonic() + 5
        while run.thread is None and time.monotonic() < deadline:
            time.sleep(0.02)
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
        # run_ids are UUID4; verify task_contract is retained instead.
        goals = {r.task_contract.get("goal") for r in runs}
        assert goals == {"one", "two"}


class TestRunManagerCancel:
    """Test run cancellation."""

    def test_cancel_created_run(self) -> None:
        """Cancelling a created run sets state to cancelled."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"}).run_id
        assert mgr.cancel_run(run_id) is True
        run = mgr.get_run(run_id)
        assert run is not None, "Expected non-None result for run"
        assert run.state == "cancelled"

    def test_cancel_completed_run_fails(self) -> None:
        """Cancelling a completed run returns False."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"}).run_id
        mgr.start_run(run_id, lambda r: "ok")
        run = mgr.get_run(run_id)
        assert run is not None, "Expected non-None result for run"
        deadline = time.monotonic() + 5
        while run.thread is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert run.thread is not None
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
            except Exception as exc:
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
            return "done"

        ids = []
        for i in range(4):
            rid = mgr.create_run({"task_id": f"r-{i}", "goal": "test"}).run_id
            ids.append(rid)
            mgr.start_run(rid, slow_executor)

        # Wait for all to finish — queue absorbs the burst.
        deadline = time.monotonic() + 10
        for rid in ids:
            run = mgr.get_run(rid)
            if run:
                while run.state in ("created",) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if run.thread:
                    while (
                        not run.thread.is_alive()
                        and run.state == "running"
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    run.thread.join(timeout=10)

        # The peak concurrent should be at most 2.
        assert peak[0] <= 2
        # All runs should complete (queued, not rejected).
        for rid in ids:
            run = mgr.get_run(rid)
            assert run is not None, "Expected non-None result for run"
            assert run.state == "completed"


class TestRunManagerQueue:
    """Test bounded queue and backoff behaviour."""

    def test_queue_absorbs_burst(self) -> None:
        """Runs beyond max_concurrent are queued and eventually execute."""
        gate = threading.Event()
        mgr = RunManager(max_concurrent=1, queue_size=4)

        def blocking_executor(run: ManagedRun) -> str:
            gate.wait(timeout=5)
            return "ok"

        ids = []
        for i in range(3):
            rid = mgr.create_run({"task_id": f"q-{i}", "goal": "test"}).run_id
            ids.append(rid)
            mgr.start_run(rid, blocking_executor)

        # Give the worker a moment to pick the first item from the queue.
        time.sleep(0.15)

        # None should be rejected — queue absorbed them.
        for rid in ids:
            run = mgr.get_run(rid)
            assert run is not None, "Expected non-None result for run"
            assert run.error != "queue_full", f"{rid} was rejected"

        # Release the gate so all runs complete.
        gate.set()

        # Wait for all runs to reach a terminal state.
        deadline = time.monotonic() + 10
        for rid in ids:
            run = mgr.get_run(rid)
            assert run is not None, "Expected non-None result for run"
            while run.state not in ("completed", "failed") and time.monotonic() < deadline:
                time.sleep(0.05)

        for rid in ids:
            run = mgr.get_run(rid)
            assert run is not None, "Expected non-None result for run"
            assert run.state == "completed", f"{rid} state={run.state} err={run.error}"

    def test_queue_full_rejects(self) -> None:
        """When queue is full, new runs are rejected with queue_full."""
        gate = threading.Event()
        mgr = RunManager(max_concurrent=1, queue_size=2)

        def blocking_executor(run: ManagedRun) -> str:
            gate.wait(timeout=5)
            return "ok"

        ids = []
        # Fill semaphore (1) + queue (2) = 3 accepted, 4th should be rejected.
        for i in range(5):
            rid = mgr.create_run({"task_id": f"qf-{i}", "goal": "test"}).run_id
            ids.append(rid)
            mgr.start_run(rid, blocking_executor)

        # At least one should be queue_full (immediate rejection).
        errors = {rid: mgr.get_run(rid).error for rid in ids}  # type: ignore[union-attr]  expiry_wave: Wave 17
        assert "queue_full" in errors.values(), f"Expected queue_full, got {errors}"

        gate.set()
        # Wait for all to reach terminal state.
        deadline = time.monotonic() + 10
        for rid in ids:
            run = mgr.get_run(rid)
            if run:
                while run.state not in ("completed", "failed") and time.monotonic() < deadline:
                    time.sleep(0.05)

    def test_pending_count_tracks(self) -> None:
        """pending_count reflects the number of queued runs."""
        gate = threading.Event()
        mgr = RunManager(max_concurrent=1, queue_size=8)

        def blocking_executor(run: ManagedRun) -> str:
            gate.wait(timeout=5)
            return "ok"

        for i in range(3):
            rid = mgr.create_run({"task_id": f"pc-{i}", "goal": "test"}).run_id
            mgr.start_run(rid, blocking_executor)

        # Give worker time to dequeue first item and block on semaphore for second.
        time.sleep(0.5)

        # At least 1 should still be pending in the queue.
        pending = mgr.pending_count
        assert pending >= 1, f"Expected pending >= 1, got {pending}"

        gate.set()
        # Wait for all to reach terminal state.
        deadline = time.monotonic() + 10
        for run in mgr.list_runs():
            while run.state not in ("completed", "failed") and time.monotonic() < deadline:
                time.sleep(0.05)

        assert mgr.pending_count == 0

    def test_get_status_reflects_reality(self) -> None:
        """get_status returns correct active/queued/capacity/utilization."""
        mgr = RunManager(max_concurrent=2, queue_size=4)
        status = mgr.get_status()
        assert status["active_runs"] == 0
        assert status["queued_runs"] == 0
        assert status["total_capacity"] == 2
        assert status["queue_utilization"] == 0.0

        gate = threading.Event()

        def blocking_executor(run: ManagedRun) -> str:
            gate.wait(timeout=5)
            return "ok"

        for i in range(4):
            rid = mgr.create_run({"task_id": f"st-{i}", "goal": "test"}).run_id
            mgr.start_run(rid, blocking_executor)

        time.sleep(0.5)
        status = mgr.get_status()
        assert status["active_runs"] <= 2
        assert status["total_capacity"] == 2
        # queue_utilization should be a float between 0 and 1
        assert 0.0 <= status["queue_utilization"] <= 1.0

        gate.set()
        deadline = time.monotonic() + 10
        for run in mgr.list_runs():
            while run.state not in ("completed", "failed") and time.monotonic() < deadline:
                time.sleep(0.05)

    def test_queued_run_eventually_executes(self) -> None:
        """A run that enters the queue completes once a slot frees up."""
        gate = threading.Event()
        results: list[str] = []
        mgr = RunManager(max_concurrent=1, queue_size=4)

        def executor(run: ManagedRun) -> str:
            gate.wait(timeout=5)
            results.append(run.run_id)
            return "done"

        rid1 = mgr.create_run({"task_id": "first", "goal": "test"}).run_id
        mgr.start_run(rid1, executor)
        time.sleep(0.15)  # let worker pick it up

        rid2 = mgr.create_run({"task_id": "second", "goal": "test"}).run_id
        mgr.start_run(rid2, executor)

        # second is queued while first is running.
        gate.set()

        deadline = time.monotonic() + 10
        for run in mgr.list_runs():
            while run.state not in ("completed", "failed") and time.monotonic() < deadline:
                time.sleep(0.05)

        assert mgr.get_run(rid1).state == "completed"  # type: ignore[union-attr]  expiry_wave: Wave 17
        assert mgr.get_run(rid2).state == "completed"  # type: ignore[union-attr]
        assert rid1 in results
        assert rid2 in results


class TestRunManagerSerialize:
    """Test serialization."""

    def test_to_dict(self) -> None:
        """to_dict produces a JSON-safe dictionary."""
        mgr = RunManager()
        run_id = mgr.create_run({"goal": "test"}).run_id
        run = mgr.get_run(run_id)
        assert run is not None, "Expected non-None result for run"
        d = mgr.to_dict(run)
        assert d["run_id"] == run_id
        assert d["state"] == "created"
        assert "thread" not in d
        # Should be JSON-serializable.
        json.dumps(d)


# ---------------------------------------------------------------------------
# HTTP API tests (using Starlette TestClient)
# ---------------------------------------------------------------------------


def _make_test_server() -> AgentServer:
    """Create a server for testing."""
    server = AgentServer(host="127.0.0.1", port=9999)
    return server


@pytest.fixture()
def client():
    """Fixture that creates a Starlette TestClient."""
    server = _make_test_server()
    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def live_server():
    """Fixture providing an AgentServer (for backward compat with test references)."""
    return _make_test_server()


class TestHealthEndpoint:
    """Test GET /health."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """Health check returns 200 with status ok and subsystems."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert "subsystems" in body
        assert "run_manager" in body["subsystems"]
        assert "timestamp" in body


class TestHealthEndpointSubsystems:
    """Detailed tests for the aggregated /health endpoint."""

    def test_all_subsystems_ok(self, client: TestClient) -> None:
        """Healthy server reports all subsystems with ok or not_configured."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        subs = body["subsystems"]
        # run_manager is always present
        assert subs["run_manager"]["status"] == "ok"
        assert "active_runs" in subs["run_manager"]
        assert "capacity" in subs["run_manager"]
        # event_bus is always present
        assert subs["event_bus"]["status"] == "ok"
        assert "subscribers" in subs["event_bus"]
        assert "dropped" in subs["event_bus"]
        # memory/metrics/context may be not_configured
        for key in ("memory", "metrics", "context"):
            assert subs[key]["status"] in ("ok", "not_configured", "error")

    def test_missing_memory_shows_not_configured(self) -> None:
        """When memory_manager is None, health reports not_configured."""
        server = AgentServer(host="127.0.0.1", port=9999)
        server.memory_manager = None
        with TestClient(server.app) as c:
            body = c.get("/health").json()
            mem = body["subsystems"]["memory"]
            assert mem["status"] == "not_configured"
            assert mem["configured"] is False

    def test_degraded_context_makes_overall_degraded(self) -> None:
        """When context health is RED, overall status is degraded."""
        from unittest.mock import MagicMock

        server = AgentServer(host="127.0.0.1", port=9999)
        mock_cm = MagicMock()
        mock_report = MagicMock()
        mock_report.health.value = "red"
        mock_cm.get_health_report.return_value = mock_report
        server.context_manager = mock_cm
        with TestClient(server.app) as c:
            body = c.get("/health").json()
            assert body["status"] == "degraded"
            assert body["subsystems"]["context"]["status"] == "degraded"
            assert body["subsystems"]["context"]["health"] == "RED"

    def test_subsystem_error_does_not_crash(self) -> None:
        """If a subsystem check raises, health still returns 200."""
        from unittest.mock import MagicMock

        server = AgentServer(host="127.0.0.1", port=9999)
        # Make metrics_collector.snapshot() raise
        mock_mc = MagicMock()
        mock_mc.snapshot.side_effect = RuntimeError("boom")
        server.metrics_collector = mock_mc
        with TestClient(server.app) as c:
            resp = c.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["subsystems"]["metrics"]["status"] == "error"
            assert body["status"] == "degraded"

    def test_response_includes_timestamp(self, client: TestClient) -> None:
        """Health response includes an ISO timestamp."""
        body = client.get("/health").json()
        ts = body["timestamp"]
        # Basic check: ISO format contains 'T' and is parseable
        assert "T" in ts
        from datetime import datetime

        datetime.fromisoformat(ts)


class TestManifestEndpoint:
    """Test GET /manifest."""

    def test_manifest_returns_info(self, client: TestClient) -> None:
        """Manifest returns system metadata."""
        resp = client.get("/manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "hi-agent"
        assert body["framework"] == "TRACE"
        assert "stages" in body
        assert "endpoints" in body


class TestRunsEndpoints:
    """Test run CRUD endpoints."""

    def test_create_and_get_run(self, client: TestClient) -> None:
        """POST /runs creates a run with UUID4 run_id, GET /runs/{id} retrieves it."""
        import uuid

        resp = client.post("/runs", json={"task_id": "abc", "goal": "test goal"})
        assert resp.status_code == 201
        body = resp.json()
        run_id = body["run_id"]
        parsed = uuid.UUID(run_id, version=4)
        assert str(parsed) == run_id
        # POST /runs returns state immediately after starting the background
        # thread; valid states are "created" (not yet picked up) or "running"
        # (thread already started).  "completed" should not appear here — if
        # the executor finishes synchronously before this line, that is a
        # test infrastructure race, not a valid contract state on POST response.
        assert body["state"] in ("created", "running")

        resp2 = client.get(f"/runs/{run_id}")
        assert resp2.status_code == 200
        assert resp2.json()["run_id"] == run_id

    def test_create_without_goal_fails(self, client: TestClient) -> None:
        """POST /runs without goal returns 400."""
        resp = client.post("/runs", json={"task_id": "x"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "missing_goal"

    def test_list_runs(self, client: TestClient) -> None:
        """GET /runs lists created runs."""
        resp1 = client.post("/runs", json={"task_id": "r1", "goal": "a"})
        resp2 = client.post("/runs", json={"task_id": "r2", "goal": "b"})
        rid1 = resp1.json()["run_id"]
        rid2 = resp2.json()["run_id"]
        resp = client.get("/runs")
        assert resp.status_code == 200
        ids = {r["run_id"] for r in resp.json()["runs"]}
        assert rid1 in ids
        assert rid2 in ids

    def test_get_nonexistent_run(self, client: TestClient) -> None:
        """GET /runs/missing returns 404."""
        resp = client.get("/runs/missing")
        assert resp.status_code == 404

    def test_signal_cancel(self, client: TestClient) -> None:
        """POST /runs/{id}/signal with cancel signal works."""
        create_resp = client.post("/runs", json={"task_id": "s1", "goal": "test"})
        run_id = create_resp.json()["run_id"]
        resp = client.post(f"/runs/{run_id}/signal", json={"signal": "cancel"})
        assert resp.status_code in (200, 409)
        if resp.status_code == 200:
            assert resp.json()["state"] == "cancelled"

    def test_signal_unknown(self, client: TestClient) -> None:
        """POST /runs/{id}/signal with unknown signal returns 400."""
        create_resp = client.post("/runs", json={"task_id": "s2", "goal": "test"})
        run_id = create_resp.json()["run_id"]
        resp = client.post(f"/runs/{run_id}/signal", json={"signal": "explode"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "unknown_signal"

    def test_not_found_routes(self, client: TestClient) -> None:
        """Unknown paths return 404."""
        resp = client.get("/nope")
        assert resp.status_code == 404
        resp2 = client.post("/nope")
        assert resp2.status_code in (404, 405)


class TestMetricsEndpoints:
    """Test metrics endpoints."""

    def test_metrics_prometheus_no_collector(self) -> None:
        """GET /metrics returns text when no collector configured."""
        server = AgentServer(host="127.0.0.1", port=9999)
        server.metrics_collector = None  # Explicitly remove to test unconfigured path
        with TestClient(server.app) as client:
            resp = client.get("/metrics")
            assert resp.status_code == 200
            assert "text/plain" in resp.headers["content-type"]
            assert "No metrics collector configured" in resp.text

    def test_metrics_json_no_collector(self) -> None:
        """GET /metrics/json returns empty dict when no collector configured."""
        server = AgentServer(host="127.0.0.1", port=9999)
        server.metrics_collector = None  # Explicitly remove to test unconfigured path
        with TestClient(server.app) as client:
            resp = client.get("/metrics/json")
            assert resp.status_code == 200
            assert resp.json() == {}


class TestAsyncEndpoint:
    """Test that async handlers work correctly."""

    def test_async_health_endpoint(self, client: TestClient) -> None:
        """Verify the async health handler responds correctly."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "subsystems" in data
        assert "timestamp" in data

    def test_async_create_and_list(self, client: TestClient) -> None:
        """Verify async create followed by list returns consistent data."""
        create_resp = client.post("/runs", json={"task_id": "async-1", "goal": "async test"})
        run_id = create_resp.json()["run_id"]
        resp = client.get("/runs")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert any(r["run_id"] == run_id for r in runs)


class TestSSEStreaming:
    """Test SSE streaming endpoint is routable."""

    def test_sse_endpoint_exists(self, client: TestClient) -> None:
        """GET /runs/{run_id}/events should return SSE media type.

        Note: Without publishing events, the stream will block.
        We test that the endpoint is routable and returns the correct
        content type by using a short timeout or by checking that the
        route is registered.
        """
        # Verify the route exists in the app routes
        app = client.app
        route_paths = []
        for route in app.routes:  # type: ignore[union-attr]  expiry_wave: Wave 17
            if hasattr(route, "path"):
                route_paths.append(route.path)
        assert "/runs/{run_id}/events" in route_paths


class TestConcurrentRequests:
    """Test that concurrent requests are handled correctly."""

    def test_concurrent_creates_via_client(self, client: TestClient) -> None:
        """Multiple concurrent POST /runs should all succeed."""
        errors: list[str] = []
        results: list[dict] = []
        lock = threading.Lock()

        def create_run(idx: int) -> None:
            try:
                resp = client.post(
                    "/runs",
                    json={"task_id": f"conc-{idx}", "goal": f"goal-{idx}"},
                )
                with lock:
                    if resp.status_code != 201:
                        errors.append(f"conc-{idx}: status={resp.status_code}")
                    else:
                        results.append(resp.json())
            except Exception as exc:
                with lock:
                    errors.append(str(exc))

        threads = [threading.Thread(target=create_run, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Errors: {errors}"
        assert len(results) == 10

        # Verify all runs are listed — IDs are UUID4, check by count.
        resp = client.get("/runs")
        assert resp.status_code == 200
        created_ids = {r["run_id"] for r in results}
        listed_ids = {r["run_id"] for r in resp.json()["runs"]}
        assert created_ids.issubset(listed_ids)


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
        args = parser.parse_args(
            [
                "run",
                "--goal",
                "summarize this",
                "--task-family",
                "analysis",
                "--risk-level",
                "medium",
                "--json",
            ]
        )
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

        with patch("sys.argv", ["hi_agent"]), pytest.raises(SystemExit):
            main()

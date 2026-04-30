"""End-to-end customer scenario tests.

These tests validate hi-agent from the outside in �?the way a real user would
interact with the system.  They go through the full HTTP API stack rather than
calling internal classes directly.

Design principle (CLAUDE.md Release Quality Protocol):
  "boot 测试通过 �?可用。只有真实执行路径跑通,才算通过�?

Every test below corresponds to something a real user would try on day one.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

from tests._helpers.run_states import TERMINAL_STATES
from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_executor_factory(*, fail_stage: str | None = None) -> Callable:
    """Return an executor factory backed by MockKernel (no real LLM/kernel needed).

    Args:
        fail_stage: If set, configure MockKernel to fail actions in this stage.
    """

    def factory(run_data: dict[str, Any]) -> Callable[[], Any]:
        task_id = run_data.get("task_id") or run_data.get("run_id") or uuid.uuid4().hex[:12]
        constraints: list[str] = []
        if fail_stage:
            constraints.append(f"fail_action:{fail_stage}")
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            constraints=constraints,
        )
        kernel = MockKernel()
        executor = RunExecutor(
            contract,
            kernel,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        return executor.execute

    return factory


def _wait_for_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    """Poll GET /runs/{run_id} until the run reaches a terminal state.

    Terminal states: completed, failed, aborted.

    Raises:
        TimeoutError: If the run does not finish within *timeout* seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200, f"Unexpected {resp.status_code} polling {run_id}"
        data = resp.json()
        if data.get("state") in TERMINAL_STATES:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Run {run_id!r} did not reach a terminal state within {timeout:.1f}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def server() -> AgentServer:
    """A fresh AgentServer wired with a MockKernel executor factory."""
    s = AgentServer()
    s.executor_factory = _make_mock_executor_factory()
    return s


@pytest.fixture()
def client(server: AgentServer) -> TestClient:
    """Starlette TestClient backed by the mock server."""
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.fixture()
def client_with_knowledge(tmp_path) -> TestClient:
    """TestClient with a real KnowledgeManager wired to a temp directory."""
    from hi_agent.knowledge.graph_renderer import GraphRenderer
    from hi_agent.knowledge.knowledge_manager import KnowledgeManager
    from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
    from hi_agent.knowledge.wiki import KnowledgeWiki
    from hi_agent.memory.long_term import LongTermMemoryGraph

    s = AgentServer()
    s.executor_factory = _make_mock_executor_factory()
    _kdir = str(tmp_path / "knowledge")
    _graph = LongTermMemoryGraph(f"{_kdir}/graph.json")
    s.knowledge_manager = KnowledgeManager(
        wiki=KnowledgeWiki(f"{_kdir}/wiki"),
        user_store=UserKnowledgeStore(f"{_kdir}/user"),
        graph=_graph,
        renderer=GraphRenderer(_graph),
    )
    return TestClient(s.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# TC01 - health check returns ok


def test_tc01_health_check_returns_ok(client: TestClient) -> None:
    """A freshly started server must report healthy before any run is submitted.

    From the user's perspective: the very first thing they do is check if the
    service is up. A non-200 or a missing 'status' field means they can't trust
    the service.
    """
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body, "Health response must contain 'status'"
    assert body["status"] in ("ok", "degraded"), f"Unexpected status: {body['status']}"
    assert "subsystems" in body
    assert "run_manager" in body["subsystems"]
    assert body["subsystems"]["run_manager"]["status"] == "ok"


# ---------------------------------------------------------------------------
# TC02 �?系统清单包含 TRACE 阶段
# ---------------------------------------------------------------------------


def test_tc02_manifest_exposes_trace_stages(client: TestClient) -> None:
    """GET /manifest must enumerate the TRACE stages so integrators know what to expect.

    Users rely on this endpoint to discover what the system can do without
    reading source code.
    """
    resp = client.get("/manifest")

    assert resp.status_code == 200
    body = resp.json()
    assert "framework" in body
    assert body["framework"] == "TRACE"
    stages = body.get("stages", [])
    assert len(stages) >= 4, "Expected at least 4 TRACE stages in manifest"

    # Strengthen: capabilities must be present (not empty default) so integrators
    # know what the platform can actually do.
    capabilities = body.get("capabilities", [])
    assert isinstance(capabilities, list), "capabilities must be a list"
    assert len(capabilities) > 0, (
        "Manifest must list at least one capability. "
        "An empty list means the manifest is not reading live runtime state."
    )


# ---------------------------------------------------------------------------
# TC03 �?提交任务 �?轮询 �?完成 (Happy Path)
# ---------------------------------------------------------------------------


def test_tc03_submit_goal_poll_completed(client: TestClient) -> None:
    """Core user journey: submit a goal, wait, get 'completed'.

    This is the absolute minimum the product must deliver. If this test fails,
    the service is not usable at all.
    """
    resp = client.post("/runs", json={"goal": "Summarise the TRACE framework"})

    assert resp.status_code == 201
    body = resp.json()
    assert "run_id" in body, "POST /runs must return run_id"
    run_id = body["run_id"]
    assert run_id, "run_id must be non-empty"

    final = _wait_for_terminal(client, run_id)

    assert final["state"] == "completed", (
        f"Expected completed, got {final['state']}. error={final.get('error')}"
    )
    assert final["run_id"] == run_id

    # Strengthen: result must be a structured dict, not just a bare status string.
    # Downstream integrators must be able to inspect stage outcomes and artifacts.
    result = final.get("result")
    assert isinstance(result, dict), (
        "result must be a structured dict consumable by downstream, "
        f"got {type(result).__name__!r}: {result!r}"
    )
    assert result.get("status") == "completed", (
        f"result.status must be 'completed', got {result.get('status')!r}"
    )
    assert "stages" in result, "result must include 'stages' list"
    assert "artifacts" in result, "result must include 'artifacts' list"


# ---------------------------------------------------------------------------
# TC04 �?同一目标两次提交得到两个不同 run_id,无 duplicate 错误
# ---------------------------------------------------------------------------


def test_tc04_two_runs_same_goal_unique_ids_no_duplicate(client: TestClient) -> None:
    """Submitting the same goal twice must produce two independent runs.

    The infamous run_id='trace' bug caused the second run to get a duplicate
    run_id and crash the service state permanently.  This test guards that
    regression forever.
    """
    goal = "Analyse quarterly revenue data"

    resp1 = client.post("/runs", json={"goal": goal})
    resp2 = client.post("/runs", json={"goal": goal})

    assert resp1.status_code == 201
    assert resp2.status_code == 201

    run_id_1 = resp1.json()["run_id"]
    run_id_2 = resp2.json()["run_id"]

    assert run_id_1 != run_id_2, (
        f"Two separate submissions must receive different run_ids. Both got: {run_id_1!r}"
    )

    final1 = _wait_for_terminal(client, run_id_1)
    final2 = _wait_for_terminal(client, run_id_2)

    assert final1["state"] == "completed"
    assert final2["state"] == "completed"

    # Service must still be healthy after both runs.
    health = client.get("/health")
    assert health.json()["status"] in ("ok", "degraded")


# ---------------------------------------------------------------------------
# TC05 - missing goal returns 400


def test_tc05_missing_goal_returns_400(client: TestClient) -> None:
    """POST /runs without 'goal' must return 400 Bad Request.

    Users will send malformed requests.  The service must reject them cleanly
    rather than crashing or returning 500.
    """
    resp = client.post("/runs", json={"task_family": "analysis"})  # no goal

    assert resp.status_code == 400
    body = resp.json()
    assert "message" in body or "error" in body  # structured or legacy error format

    # Service must still be healthy after the bad request.
    health = client.get("/health")
    assert health.status_code == 200


# ---------------------------------------------------------------------------
# TC06 - list submitted runs


def test_tc06_list_runs_shows_all_submitted(client: TestClient) -> None:
    """GET /runs must return every run that was submitted this session.

    A user who has submitted several tasks needs to be able to see their full
    work history in a single call.
    """
    goals = [
        "Write a Python hello-world script",
        "Explain gradient descent",
        "Draft a project status email",
    ]
    submitted_ids: set[str] = set()

    for goal in goals:
        resp = client.post("/runs", json={"goal": goal})
        assert resp.status_code == 201
        submitted_ids.add(resp.json()["run_id"])

    # Wait for all runs to settle before listing.
    for run_id in submitted_ids:
        _wait_for_terminal(client, run_id)

    list_resp = client.get("/runs")
    assert list_resp.status_code == 200
    runs = list_resp.json().get("runs", [])
    listed_ids = {r["run_id"] for r in runs}

    for sid in submitted_ids:
        assert sid in listed_ids, f"run_id {sid!r} not found in GET /runs response"


# ---------------------------------------------------------------------------
# TC07 �?查询不存在的 run_id 返回 404
# ---------------------------------------------------------------------------


def test_tc07_unknown_run_id_returns_404(client: TestClient) -> None:
    """GET /runs/{nonexistent-id} must return 404, not 500.

    Users make typos.  The service must distinguish 'not found' from 'crashed'.
    """
    resp = client.get("/runs/does-not-exist-xyz-999")

    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body or "detail" in body


# ---------------------------------------------------------------------------
# TC08 �?任务失败时服务不崩溃,状态为 failed
# ---------------------------------------------------------------------------


def test_tc08_run_failure_service_stays_healthy() -> None:
    """A task that fails must leave the service fully operational.

    This catches the 'NoneType has no attribute max_attempts' class of bugs
    where the failure-handling path itself crashes, leaving the service in an
    unrecoverable state.
    """
    s = AgentServer()
    s.executor_factory = _make_mock_executor_factory(fail_stage="S3_build")
    c = TestClient(s.app, raise_server_exceptions=False)

    resp = c.post("/runs", json={"goal": "Task that will fail"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    final = _wait_for_terminal(c, run_id)

    # Rule 7: this test injected fail_stage="S3_build"; the run MUST fail.
    # Accepting "completed" here would mask a defect where fail_stage is ignored.
    assert final["state"] == "failed", (
        f"Run with injected fail_stage must terminate as failed, got {final['state']!r}"
    )

    # CRITICAL: the service must still respond to health checks after the failure.
    health = c.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] in ("ok", "degraded")

    # And must still accept new runs.
    resp2 = c.post("/runs", json={"goal": "Second run after failure"})
    assert resp2.status_code == 201


# ---------------------------------------------------------------------------
# TC09 �?并发提交三个任务,全部独立完成,run_id 互不相同
# ---------------------------------------------------------------------------


def test_tc09_concurrent_runs_isolated(client: TestClient) -> None:
    """Three concurrent runs must each complete independently with unique IDs.

    This validates run-level isolation: one run's state cannot contaminate
    another.  The RunContextManager and per-run state must be truly separate.
    """
    import threading

    results: list[dict] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def submit_and_collect(goal: str) -> None:
        try:
            resp = client.post("/runs", json={"goal": goal})
            assert resp.status_code == 201
            run_id = resp.json()["run_id"]
            final = _wait_for_terminal(client, run_id)
            with lock:
                results.append(final)
        except Exception as exc:
            with lock:
                errors.append(exc)

    goals = [
        "Analyse dataset A",
        "Analyse dataset B",
        "Analyse dataset C",
    ]
    threads = [threading.Thread(target=submit_and_collect, args=(g,)) for g in goals]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Errors during concurrent runs: {errors}"
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    run_ids = [r["run_id"] for r in results]
    assert len(set(run_ids)) == 3, f"Duplicate run_ids in concurrent runs: {run_ids}"

    for r in results:
        # Rule 7: concurrent normal runs (no failure injection) must complete.
        assert r["state"] == "completed", f"Run {r['run_id']!r} must complete, got {r['state']!r}"


# ---------------------------------------------------------------------------
# TC10 - cancel signal terminates run

# Reason: cancel test validates reachability of any terminal state (non-deterministic outcome)
_TERMINAL_STATES = TERMINAL_STATES


def test_tc10_cancel_signal_terminates_run(client: TestClient) -> None:
    """POST /runs/{id}/signal with 'cancel' must drive run to a terminal state.

    The cancel contract: a cancel signal must be accepted, and the run must
    eventually reach *some* terminal state.  The specific terminal state is
    non-deterministic (may race to completed, aborted, or cancelled) — this
    test asserts reachability of a terminal state, not a specific outcome.
    A separate failure-injection test covers the explicit 'failed' path.
    """
    resp = client.post("/runs", json={"goal": "Long analysis task"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    # Send cancel signal.
    sig_resp = client.post(f"/runs/{run_id}/signal", json={"signal": "cancel"})
    # Acceptable: 200 (cancelled), 409 (already terminal), 404 (not found yet)
    assert sig_resp.status_code in (200, 404, 409), (
        f"Unexpected status {sig_resp.status_code} sending cancel signal"
    )

    # _wait_for_terminal raises TimeoutError if terminal is not reached.
    final = _wait_for_terminal(client, run_id, timeout=15.0)
    assert final["state"] == "cancelled", (
        f"Expected state='cancelled' after cancel signal, got {final['state']!r}. "
        "A cancel signal must drive the run to state='cancelled', not another terminal state."
    )


def test_tc10_failure_scenario(client: TestClient) -> None:
    """A run configured to fail must reach state='failed' (not 'completed').

    This is the failure-path complement to the cancel test above.  It uses
    explicit failure injection (fail_action constraint on MockKernel) so the
    outcome is deterministic.
    """
    from hi_agent.server.app import AgentServer

    fail_server = AgentServer()
    fail_server.executor_factory = _make_mock_executor_factory(fail_stage="analyze_goal")

    with TestClient(fail_server.app, raise_server_exceptions=False) as fail_client:
        resp = fail_client.post("/runs", json={"goal": "trigger failure"})
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        final = _wait_for_terminal(fail_client, run_id, timeout=15.0)
        assert final["state"] == "failed", (
            f"Failure-injected run must reach state='failed', got {final['state']!r}"
        )


# ---------------------------------------------------------------------------
# TC11 �?SSE 事件流为有效格式
# ---------------------------------------------------------------------------


def test_tc11_sse_endpoint_returns_correct_content_type(
    client: TestClient,
) -> None:
    """GET /runs/{id}/events must return Content-Type: text/event-stream.

    Users and client libraries detect SSE streams by Content-Type.  A wrong
    or missing header means the browser/SDK won't treat the response as SSE.

    We make an actual HTTP request and inspect the Content-Type response header.
    Previous version of this test inspected source code text — that does not
    verify runtime behavior.

    Note: We verify headers only. Reading the SSE body in a test client
    requires a running event loop�?full SSE flow is covered by manual
    integration testing against a live server (see CLAUDE.md §Customer View).
    """
    # Submit a run so the run_id exists in the server.
    resp = client.post("/runs", json={"goal": "SSE header check"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    # Verify the Content-Type header by calling the route handler directly.
    #
    # client.stream() would block forever: the SSE endpoint's async generator
    # awaits asyncio.Queue.get() in an infinite loop so the ASGI transport
    # never sees end-of-body.  Going through the full HTTP stack is not needed
    # here — what matters is that the handler returns StreamingResponse with
    # media_type="text/event-stream", which Starlette faithfully maps to the
    # Content-Type header.
    #
    # We call the async handler synchronously from this sync test via
    # asyncio.run().  The handler body does not await anything; it only
    # constructs and returns the StreamingResponse object.  The generator is
    # not iterated — only .media_type is read.
    #
    # The handler requires two pieces of context that are normally injected by
    # middleware before the route handler runs:
    #   1. TenantContext — set by AuthMiddleware (anonymous when auth disabled)
    #   2. request.app — needed to access app.state.agent_server
    # Both must be supplied when calling the handler directly.
    from hi_agent.server.app import handle_run_events_sse
    from hi_agent.server.tenant_context import (
        TenantContext,
        reset_tenant_context,
        set_tenant_context,
    )
    from starlette.requests import Request as StarletteRequest

    # Mirror the anonymous context that AuthMiddleware injects when auth is disabled.
    anon_ctx = TenantContext(
        tenant_id="__anonymous__",
        user_id="__anonymous__",
        session_id="__anonymous__",
        auth_method="none",
    )
    _token = set_tenant_context(anon_ctx)
    try:
        scope = {
            "type": "http",
            "method": "GET",
            "path": f"/runs/{run_id}/events",
            "path_params": {"run_id": run_id},
            "query_string": b"",
            "headers": [],
            "app": client.app,  # required for request.app.state.agent_server
        }
        sse_response = asyncio.run(handle_run_events_sse(StarletteRequest(scope)))
    finally:
        reset_tenant_context(_token)

    media_type = sse_response.media_type or ""
    assert "text/event-stream" in media_type, (
        f"SSE endpoint must return Content-Type: text/event-stream, got {media_type!r}"
    )

    # Also verify the route is registered at the right path.
    routes = {
        getattr(r, "path", None): r
        for r in client.app.routes  # type: ignore[union-attr]  expiry_wave: Wave 17
    }
    sse_path = "/runs/{run_id}/events"
    assert sse_path in routes, (
        f"SSE route {sse_path!r} not found. Registered paths: {list(routes.keys())}"
    )


# ---------------------------------------------------------------------------
# TC12 �?知识库:摄入后可查到
# ---------------------------------------------------------------------------


def test_tc12_knowledge_ingest_then_query(client_with_knowledge: TestClient) -> None:
    """Ingested knowledge must be retrievable through the query endpoint.

    A user who loads domain knowledge into the system expects that the agent
    will be able to find it when asked.
    """
    # Ingest a page.
    ingest_resp = client_with_knowledge.post(
        "/knowledge/ingest",
        json={
            "title": "TRACE Framework Overview",
            "content": (
                "TRACE stands for Task Route Act Capture Evolve. "
                "It is an enterprise-grade intelligent agent framework."
            ),
            "tags": ["trace", "framework"],
        },
    )
    assert ingest_resp.status_code in (200, 201), (
        f"Ingest failed: {ingest_resp.status_code} {ingest_resp.text}"
    )
    assert ingest_resp.json().get("status") == "created"

    # Query for it.
    query_resp = client_with_knowledge.get(
        "/knowledge/query",
        params={"q": "TRACE framework", "limit": "5"},
    )
    assert query_resp.status_code == 200
    body = query_resp.json()
    assert "query" in body
    # The ingested content should surface in the results.
    context = body.get("context", "") or ""
    assert "TRACE" in context or body.get("total_results", 0) > 0, (
        "Ingested knowledge not found in query results"
    )


# ---------------------------------------------------------------------------
# TC13 - knowledge status response shape


def test_tc13_knowledge_status_format(client_with_knowledge: TestClient) -> None:
    """GET /knowledge/status must return a valid stats response.

    Operations teams monitor knowledge base growth.  An empty or malformed
    response breaks their dashboards.
    """
    resp = client_with_knowledge.get("/knowledge/status")

    assert resp.status_code == 200
    body = resp.json()
    # Must contain at least one numeric size indicator.
    numeric_fields = {k: v for k, v in body.items() if isinstance(v, (int, float))}
    assert numeric_fields, f"Knowledge status response has no numeric fields: {body}"


# ---------------------------------------------------------------------------
# TC14 �?成本追踪端点在多次运行后可用
# ---------------------------------------------------------------------------


def test_tc14_cost_tracking_after_runs(client: TestClient) -> None:
    """GET /cost must return a valid cost breakdown after runs complete.

    Users who care about LLM spend need this endpoint to be reliable.
    It must not crash and must return a structured response.
    """
    # Submit and complete a couple of runs to generate cost records.
    for goal in ("Cost test run A", "Cost test run B"):
        resp = client.post("/runs", json={"goal": goal})
        assert resp.status_code == 201
        _wait_for_terminal(client, resp.json()["run_id"])

    cost_resp = client.get("/cost")

    assert cost_resp.status_code == 200
    body = cost_resp.json()
    # Must include at minimum a total cost field.
    assert "total_usd" in body, f"Cost response missing 'total_usd': {body}"
    assert isinstance(body["total_usd"], (int, float))


# ---------------------------------------------------------------------------
# TC15 �?健康检查在服务有任务历史后仍然正常
# ---------------------------------------------------------------------------


def test_tc15_health_stable_after_mixed_workload() -> None:
    """Health endpoint must return 'ok' even after a mix of successful and failed runs.

    This is the final integration check: simulate a realistic session where
    some tasks succeed and some fail, then confirm the service is still clean.
    """
    s = AgentServer()
    run_count = [0]

    def alternating_factory(run_data: dict[str, Any]) -> Callable[[], Any]:
        """Alternates: even runs succeed, odd runs use a failing stage."""
        run_count[0] += 1
        fail = run_count[0] % 2 == 0
        return _make_mock_executor_factory(fail_stage="S3_build" if fail else None)(run_data)

    s.executor_factory = alternating_factory
    c = TestClient(s.app, raise_server_exceptions=False)

    run_ids: list[str] = []
    for i in range(4):
        resp = c.post("/runs", json={"goal": f"Mixed workload task {i}"})
        assert resp.status_code == 201
        run_ids.append(resp.json()["run_id"])

    # Rule 7: alternating_factory increments run_count on each call; call #N
    # fails iff N is even.  Assert the exact expected outcome per index rather
    # than accepting either terminal state.
    for idx, run_id in enumerate(run_ids, start=1):
        final = _wait_for_terminal(c, run_id)
        expected = "failed" if (idx % 2 == 0) else "completed"
        assert final["state"] == expected, (
            f"Run {run_id!r} (call #{idx}) expected {expected!r}, got {final['state']!r}"
        )

    # After all that, the service must be fully operational.
    health = c.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] in ("ok", "degraded")

    # Must still accept new work.
    fresh = c.post("/runs", json={"goal": "Final post-chaos run"})
    assert fresh.status_code == 201
    final_run = _wait_for_terminal(c, fresh.json()["run_id"])
    # Rule 7: this is call #5 on alternating_factory (odd) → no fail_stage
    # injected, so the run MUST complete.
    assert final_run["state"] == "completed", (
        f"Post-chaos run (call #5, odd → no fail) must complete, got {final_run['state']!r}"
    )

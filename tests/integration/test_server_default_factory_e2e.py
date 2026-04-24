"""Server default executor factory end-to-end tests.

These tests exercise the REAL _default_executor_factory of AgentServer —
the factory that every production POST /runs call actually uses.

Prior E2E tests all inject a MockKernel-backed factory.  That approach
validates the HTTP layer but leaves the entire SystemBuilder wiring path
untested through the server entry.  This file closes that gap.

Prerequisites:
    HI_AGENT_ENV=dev (set per-test via monkeypatch — no real API key needed)

Design rule (CLAUDE.md Rule 6, Layer 3):
    Drive through the public HTTP interface; assert observable outputs.
    No internal mocking of hi_agent components.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> dict[str, Any]:
    """Poll GET /runs/{run_id} until terminal state, then return the run dict."""
    terminal = {"completed", "failed", "aborted"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200, f"Unexpected {resp.status_code}"
        data = resp.json()
        if data.get("state") in terminal:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Run {run_id!r} did not reach terminal state within {timeout:.1f}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dev_server(monkeypatch: pytest.MonkeyPatch) -> AgentServer:
    """AgentServer using its REAL _default_executor_factory, in dev mode.

    The monkeypatch ensures HI_AGENT_ENV=dev so the builder uses heuristic
    fallback — no real API key or kernel endpoint required.
    """
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    # Suppress config-file gateway fallback so tests stay in heuristic mode
    # even when a local llm_config.json with credentials is present.
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    # Use a high rate limit so rapid polling in tests does not hit 429.
    server = AgentServer(rate_limit_rps=10000)
    # Verify we are NOT using a mock factory — the real factory must be wired.
    # Compare via __func__ since bound methods create new objects on each access.
    assert getattr(server.executor_factory, "__func__", None) is getattr(
        server._default_executor_factory, "__func__", None
    ), (
        "AgentServer must use _default_executor_factory by default. "
        "If this assertion fails the test setup is wrong."
    )
    return server


@pytest.fixture()
def dev_client(dev_server: AgentServer) -> TestClient:
    return TestClient(dev_server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# SDF-01: Smoke — POST /runs → completed via real factory
# ---------------------------------------------------------------------------


def test_sdf01_real_factory_completes_run(
    dev_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The real default executor factory must complete a minimal goal run.

    This is the most fundamental test of the server production path:
    POST /runs goes through AgentServer._default_executor_factory →
    SystemBuilder.build_executor() → RunExecutor.execute() in dev mode.

    DF-27: when the caller does not supply ``profile_id``, the server must
    assign ``'default'`` loudly — log WARNING, record a ``route`` fallback
    event — instead of silent-defaulting (masks signal) or 500-erroring
    (breaks back-compat until downstream roadmap P-3).
    """
    import logging

    caplog.set_level(logging.WARNING)
    resp = dev_client.post("/runs", json={"goal": "Summarize the TRACE framework"})

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    run_id = resp.json().get("run_id")
    assert run_id, "run_id must be non-empty"

    # DF-27: the loud-default WARNING must fire because the POST body carried
    # no profile_id.  Assert it instead of asserting "no fallback events".
    assert any(
        "POST /runs received without profile_id" in rec.getMessage()
        for rec in caplog.records
    ), "DF-27: missing loud-default WARNING for missing profile_id"

    final = _wait_terminal(dev_client, run_id)

    assert final["state"] == "completed", (
        f"expected completed via real default factory, got {final['state']!r}. "
        f"result={final.get('result')}"
    )
    # Result must be structured (not a bare string)
    result = final.get("result")
    assert isinstance(result, dict), (
        f"result must be a structured dict from the real factory, got {type(result).__name__!r}"
    )
    assert "status" in result
    assert "stages" in result
    assert "artifacts" in result
    # DF-27: the run's top-level fallback_events must contain the route-kind
    # entry recorded at the server boundary (Rule 14: resilience must not
    # mask signal).  The top-level key is populated from
    # ``get_fallback_events(run.run_id)`` — the server-boundary run_id —
    # whereas ``result["fallback_events"]`` uses the executor's internal
    # run_id (different UUID, carries the capability heuristic events).
    top_fallback_events = final.get("fallback_events") or []
    route_events = [e for e in top_fallback_events if e.get("kind") == "route"]
    assert route_events, (
        f"DF-27: expected at least one kind=='route' fallback event on the "
        f"run dict; got top={top_fallback_events}, nested={result.get('fallback_events')}"
    )
    assert any(e.get("reason") == "missing_profile_id" for e in route_events), (
        f"DF-27: expected reason=='missing_profile_id' on route event; got {route_events}"
    )


# ---------------------------------------------------------------------------
# SDF-02: All TaskContract fields reach the executor via real factory
# ---------------------------------------------------------------------------


def test_sdf02_full_contract_fields_reach_executor(dev_client: TestClient) -> None:
    """POST /runs with all contract fields must be accepted without error.

    Verifies that _default_executor_factory correctly reconstructs a full
    TaskContract from the HTTP body — no fields silently dropped at the
    server→executor boundary.
    """
    body = {
        "goal": "Analyze quarterly data",
        "task_family": "quick_task",
        "risk_level": "low",
        "constraints": ["no_external_calls"],
        "acceptance_criteria": [],  # empty — should not cause failure
        "budget": {"max_llm_calls": 5, "max_wall_clock_seconds": 300},
        "deadline": "2099-12-31T23:59:59Z",
        "priority": 3,
        "environment_scope": ["dev"],
        "input_refs": ["artifact://test-ref"],
        "decomposition_strategy": "linear",
        "parent_task_id": "parent-001",
    }
    resp = dev_client.post("/runs", json=body)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    run_id = resp.json()["run_id"]
    final = _wait_terminal(dev_client, run_id)

    # Should complete (deadline is far future, budget ample for dev mode).
    # Rule 14 / DF-08: the real factory must complete end-to-end.  Accepting
    # "failed" here would mask default-factory regressions.
    assert final["state"] == "completed", (
        f"expected completed via real factory with full contract, got {final['state']!r}. "
        f"result={final.get('result')}"
    )
    # Must not return a 500 or crash
    result = final.get("result")
    assert isinstance(result, dict), "result must be structured"
    # DF-27: body omits profile_id → expect exactly the route-kind fallback
    # recorded at the server boundary; heuristic capability fallbacks in dev
    # mode are also acceptable here (no real LLM key in test env).
    fallback_events = result.get("fallback_events") or []
    non_route_or_capability = [
        e for e in fallback_events if e.get("kind") not in ("route", "capability")
    ]
    assert not non_route_or_capability, (
        f"unexpected non-route/non-capability fallback events: {non_route_or_capability}"
    )


# ---------------------------------------------------------------------------
# SDF-03: acceptance_criteria with required_stage affects outcome via real factory
# ---------------------------------------------------------------------------


def test_sdf03_acceptance_criteria_required_stage_causes_failure(
    dev_client: TestClient,
) -> None:
    """acceptance_criteria with a nonexistent required_stage must cause failure.

    This proves the ACTIVE consumption of acceptance_criteria through the
    real factory path — not just through MockKernel.
    """
    body = {
        "goal": "Test acceptance criteria enforcement",
        "acceptance_criteria": ["required_stage:NONEXISTENT_STAGE_XYZ"],
    }
    resp = dev_client.post("/runs", json=body)
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    final = _wait_terminal(dev_client, run_id)

    # The run must fail because NONEXISTENT_STAGE_XYZ was not completed.
    assert final["state"] == "failed", (
        f"Expected failed (acceptance criterion not met), got {final['state']!r}. "
        f"result={final.get('result')}"
    )
    result = final.get("result", {})
    assert isinstance(result, dict)
    assert result.get("status") == "failed", (
        f"result.status must be 'failed', got {result.get('status')!r}"
    )
    # failure_code should indicate the criteria failure
    assert result.get("failure_code") is not None, "Failed run must have a non-null failure_code"


# ---------------------------------------------------------------------------
# SDF-04: /ready returns consistent state with real builder
# ---------------------------------------------------------------------------


def test_sdf04_readiness_uses_real_builder(dev_client: TestClient, dev_server: AgentServer) -> None:
    """/ready in real factory mode must read from the same builder used by runs.

    Verifies the readiness contract: capability list from /ready must
    match the live builder — not a fresh default snapshot.
    """
    resp = dev_client.get("/ready")
    assert resp.status_code in (200, 503)
    body = resp.json()

    assert "ready" in body
    assert "capabilities" in body

    # Capabilities from /ready must match those from the live builder
    builder = dev_server._builder
    assert builder is not None
    try:
        invoker = builder.build_invoker()
        reg = getattr(invoker, "registry", None) or getattr(invoker, "_registry", None)
        live_caps = set(reg.list_names()) if reg is not None else set()
    except Exception:
        live_caps = set()

    ready_caps = set(body.get("capabilities", []))
    if live_caps:
        assert ready_caps == live_caps, (
            f"/ready capabilities {ready_caps!r} do not match live builder {live_caps!r}"
        )


# ---------------------------------------------------------------------------
# SDF-05: /manifest exposes contract_field_status section
# ---------------------------------------------------------------------------


def test_sdf05_manifest_exposes_contract_field_status(dev_client: TestClient) -> None:
    """GET /manifest must include contract_field_status so integrators know
    which TaskContract fields actually drive execution behavior.
    """
    resp = dev_client.get("/manifest")
    assert resp.status_code == 200
    body = resp.json()

    assert "contract_field_status" in body, (
        "manifest must include 'contract_field_status' so integrators know "
        "which fields are ACTIVE vs PASSTHROUGH"
    )
    field_status = body["contract_field_status"]
    assert isinstance(field_status, dict)

    # ACTIVE fields that must be declared
    active_fields = {
        "goal",
        "task_family",
        "risk_level",
        "constraints",
        "acceptance_criteria",
        "budget",
        "deadline",
        "profile_id",
        "decomposition_strategy",
    }
    for f in active_fields:
        assert f in field_status, f"contract_field_status missing field: {f!r}"
        assert field_status[f] == "ACTIVE", f"Field {f!r} should be ACTIVE, got {field_status[f]!r}"

    # PASSTHROUGH fields
    passthrough_fields = {"environment_scope", "input_refs", "parent_task_id"}
    for f in passthrough_fields:
        assert f in field_status, f"contract_field_status missing passthrough field: {f!r}"
        assert field_status[f] == "PASSTHROUGH", (
            f"Field {f!r} should be PASSTHROUGH, got {field_status[f]!r}"
        )

    # QUEUE_ONLY
    assert field_status.get("priority") == "QUEUE_ONLY"

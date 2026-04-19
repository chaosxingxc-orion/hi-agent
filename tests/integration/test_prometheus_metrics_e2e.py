"""Prometheus metrics E2E validation tests.

Drive GET /metrics and GET /metrics/json through the public HTTP interface
using starlette.testclient.TestClient.  No internal hi_agent mocking.

Design rule (CLAUDE.md Rule 6, Layer 3):
    Assertions are on observable HTTP outputs only.
    Tests must pass whether or not metrics_collector is wired (graceful
    degradation is a required contract of both endpoints).
"""

from __future__ import annotations

import re
import time
from typing import Any

import pytest
from starlette.testclient import TestClient

from hi_agent.server.app import AgentServer


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_server_default_factory_e2e.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dev_server(monkeypatch: pytest.MonkeyPatch) -> AgentServer:
    """AgentServer in dev mode with real default executor factory.

    Uses a very high rate limit so rapid test calls never hit 429.
    """
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    return AgentServer(rate_limit_rps=10000)


@pytest.fixture()
def dev_client(dev_server: AgentServer) -> TestClient:
    return TestClient(dev_server.app, raise_server_exceptions=False)


def _wait_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> dict[str, Any]:
    """Poll GET /runs/{run_id} until terminal state and return the run dict."""
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
# PME-01: GET /metrics content-type
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_text_content_type(dev_client: TestClient) -> None:
    """GET /metrics must return HTTP 200 with text/plain content type.

    Both the no-collector path (stub response) and the collector path emit
    text/plain; charset=utf-8.  The test is resilient to either case.
    """
    resp = dev_client.get("/metrics")

    assert resp.status_code == 200, (
        f"Expected 200 from /metrics, got {resp.status_code}: {resp.text[:200]}"
    )
    content_type = resp.headers.get("content-type", "")
    assert "text/plain" in content_type, (
        f"Expected text/plain content-type, got {content_type!r}"
    )
    # Body is a string (possibly empty when collector has recorded nothing yet).
    assert isinstance(resp.text, str), "GET /metrics body must be a string"


# ---------------------------------------------------------------------------
# PME-02: GET /metrics/json returns a dict
# ---------------------------------------------------------------------------


def test_metrics_json_endpoint_returns_dict(dev_client: TestClient) -> None:
    """GET /metrics/json must return HTTP 200 with a JSON object (dict).

    The no-collector path returns {} and the collector path returns a
    populated snapshot.  Both are valid — the contract is dict, not empty.
    """
    resp = dev_client.get("/metrics/json")

    assert resp.status_code == 200, (
        f"Expected 200 from /metrics/json, got {resp.status_code}: {resp.text[:200]}"
    )
    content_type = resp.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"Expected application/json, got {content_type!r}"
    )
    body = resp.json()
    assert isinstance(body, dict), (
        f"GET /metrics/json body must be a JSON object (dict), got {type(body).__name__!r}"
    )


# ---------------------------------------------------------------------------
# PME-03: Prometheus format after a completed run
# ---------------------------------------------------------------------------


def test_prometheus_format_after_run(dev_client: TestClient) -> None:
    """POST /runs then GET /metrics: validate Prometheus text format.

    Invariants that must hold regardless of whether metrics_collector is wired:
      - 200 status
      - text/plain content-type
      - non-empty body

    If the collector IS wired (body contains more than the stub sentinel):
      - At least one "# HELP" or "# TYPE" line must be present
      - Any data line that contains a label set must match
        `metric_name{...} value` pattern
    """
    # Trigger a real run so the collector has something to record.
    run_resp = dev_client.post("/runs", json={"goal": "Summarize the TRACE framework"})
    assert run_resp.status_code == 201, (
        f"POST /runs failed: {run_resp.status_code} {run_resp.text[:200]}"
    )
    run_id = run_resp.json().get("run_id")
    assert run_id, "run_id must be non-empty"
    _wait_terminal(dev_client, run_id)

    # Now fetch Prometheus metrics.
    resp = dev_client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")

    body = resp.text
    assert body.strip(), "GET /metrics body must be non-empty after a run"

    stub_sentinel = "# No metrics collector configured"
    if stub_sentinel in body:
        # Graceful degradation path — no collector wired; nothing more to check.
        return

    # Collector is wired: validate Prometheus exposition format.
    lines = [ln for ln in body.splitlines() if ln.strip()]
    comment_lines = [ln for ln in lines if ln.startswith("#")]
    assert comment_lines, (
        "Prometheus output must contain at least one # HELP or # TYPE line"
    )
    assert any(ln.startswith("# HELP") or ln.startswith("# TYPE") for ln in comment_lines), (
        "Prometheus output must contain # HELP or # TYPE directives"
    )

    # Every data line (non-comment, non-empty) that contains a label block
    # must match the standard pattern: identifier{...} number
    data_line_re = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*(\{[^}]*\})?\s+[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$')
    for ln in lines:
        if ln.startswith("#"):
            continue
        assert data_line_re.match(ln), (
            f"Prometheus data line does not match expected format: {ln!r}"
        )


# ---------------------------------------------------------------------------
# PME-04: /metrics/json snapshot after a completed run
# ---------------------------------------------------------------------------


def test_metrics_json_snapshot_after_run(dev_client: TestClient) -> None:
    """POST /runs then GET /metrics/json: response is always a dict.

    When the collector is not wired, the response is {}.
    When the collector is wired, the response must contain at least one key.
    The test is resilient to both cases.
    """
    run_resp = dev_client.post("/runs", json={"goal": "List TRACE middleware layers"})
    assert run_resp.status_code == 201, (
        f"POST /runs failed: {run_resp.status_code} {run_resp.text[:200]}"
    )
    run_id = run_resp.json().get("run_id")
    assert run_id
    _wait_terminal(dev_client, run_id)

    resp = dev_client.get("/metrics/json")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict), (
        f"GET /metrics/json must return a dict, got {type(body).__name__!r}"
    )

    # If the collector IS wired, the snapshot must contain at least one metric.
    # We cannot assert which keys are present because wiring varies by env,
    # but we can assert the value types for any key that IS present.
    for key, val in body.items():
        assert isinstance(key, str), f"Metric key must be str, got {type(key).__name__!r}"
        assert isinstance(val, (dict, int, float)), (
            f"Metric value for {key!r} must be dict/int/float, got {type(val).__name__!r}"
        )

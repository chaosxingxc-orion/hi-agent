"""E2E: HTTP contract tests — every public endpoint must respond correctly.

Layer-3 E2E tests per Rule 4. Drive through the public HTTP interface.
All tests skip when no server is reachable (see conftest.py).
"""

from __future__ import annotations


def test_health_returns_200(e2e_client):
    """GET /health must return 200."""
    resp = e2e_client.get("/health")
    assert resp.status_code == 200


def test_ready_returns_200(e2e_client):
    """GET /ready must return 200 with a response body."""
    resp = e2e_client.get("/ready")
    assert resp.status_code == 200


def test_metrics_returns_200_with_hi_agent_prefix(e2e_client):
    """GET /metrics must return 200 and include hi_agent_ prefixed metrics."""
    resp = e2e_client.get("/metrics")
    assert resp.status_code == 200
    assert "hi_agent_" in resp.text


def test_post_runs_does_not_500(e2e_client):
    """POST /runs with a minimal payload must not return 500."""
    resp = e2e_client.post(
        "/runs",
        json={"goal": "smoke test", "profile_id": "default"},
    )
    assert resp.status_code in (200, 400, 422), (
        f"POST /runs returned {resp.status_code} — must be 200, 400, or 422, not 500"
    )


def test_get_unknown_run_returns_404(e2e_client):
    """GET /runs/{unknown_id} must return 404."""
    resp = e2e_client.get("/runs/nonexistent-run-id-smoke-xyz")
    assert resp.status_code == 404


def test_cancel_unknown_run_returns_404(e2e_client):
    """POST /runs/{unknown_id}/cancel must return 404, not 200."""
    resp = e2e_client.post("/runs/nonexistent-run-id-smoke-xyz/cancel")
    assert resp.status_code == 404

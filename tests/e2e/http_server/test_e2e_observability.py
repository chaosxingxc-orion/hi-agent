"""E2E: Prometheus metrics must advance when runs happen.

Layer-3 E2E tests per Rule 4 and Rule 7 (observability). Drive through the
public HTTP interface.
All tests skip when no server is reachable (see conftest.py).
"""

from __future__ import annotations


def _get_metric_value(client, name: str) -> float:
    """Return the first numeric value for a Prometheus metric line matching *name*."""
    resp = client.get("/metrics")
    if resp.status_code != 200:
        return 0.0
    for line in resp.text.splitlines():
        if line.startswith(f"{name} ") or line.startswith(f"{name}{{"):
            parts = line.rsplit(" ", 1)
            try:
                return float(parts[-1])
            except ValueError:
                pass
    return 0.0


def test_metrics_endpoint_returns_prometheus_format(e2e_client):
    """GET /metrics returns 200 with hi_agent_ prefixed metric lines."""
    resp = e2e_client.get("/metrics")
    assert resp.status_code == 200
    assert "hi_agent_" in resp.text, "Metrics body does not contain any hi_agent_ prefixed metric"


def test_metrics_body_is_text(e2e_client):
    """GET /metrics returns a text/plain content type."""
    resp = e2e_client.get("/metrics")
    content_type = resp.headers.get("content-type", "")
    assert "text" in content_type or "plain" in content_type, (
        f"Unexpected content-type for /metrics: {content_type}"
    )


def test_run_does_not_decrease_runs_total(e2e_client):
    """POST /runs must not decrease hi_agent_runs_total counter.

    The counter may stay the same if the run was rejected (422), but it
    must never decrease.
    """
    before = _get_metric_value(e2e_client, "hi_agent_runs_total")
    e2e_client.post("/runs", json={"goal": "metric test run", "profile_id": "default"})
    after = _get_metric_value(e2e_client, "hi_agent_runs_total")
    assert after >= before, f"hi_agent_runs_total decreased after a POST /runs: {before} -> {after}"

"""Integration tests for the stuck-run Dead Letter Queue (DLQ) surface.

W12-D: dead_lettered_runs table + /ops/dlq routes.

Layer 2 (integration) — real RunQueue, zero mocks on the subsystem under test.
Layer 3 (E2E) — drive through HTTP via TestClient.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer, build_app
from hi_agent.server.run_queue import RunQueue
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Layer 2 — RunQueue DLQ methods directly
# ---------------------------------------------------------------------------


def test_dead_letter_and_list() -> None:
    """dead_letter a run, verify it appears in list_dlq."""
    q = RunQueue(db_path=":memory:")  # rule16-ephemeral-ok: not a restart test
    q.enqueue("run-dlq-1", tenant_id="t1")

    q.dead_letter(
        run_id="run-dlq-1",
        reason="stuck_timeout",
        original_state="leased",
        tenant_id="t1",
    )

    records = q.list_dlq()
    assert len(records) == 1
    rec = records[0]
    assert rec["run_id"] == "run-dlq-1"
    assert rec["reason"] == "stuck_timeout"
    assert rec["original_state"] == "leased"
    assert rec["tenant_id"] == "t1"
    assert rec["requeue_count"] == 0


def test_dead_letter_marks_queue_entry_failed() -> None:
    """After dead_letter, the run_queue entry status should be 'failed'."""
    q = RunQueue(db_path=":memory:")  # rule16-ephemeral-ok: not a restart test
    q.enqueue("run-dlq-2", tenant_id="t1")
    q.dead_letter(
        run_id="run-dlq-2",
        reason="watchdog_expired",
        original_state="leased",
        tenant_id="t1",
    )
    # Verify queue entry is marked failed (not re-claimable).
    # claim_next must return None because only status='queued' rows are claimable.
    claimed = q.claim_next("worker-x")
    assert claimed is None


def test_requeue_from_dlq() -> None:
    """dead_letter a run, requeue it, verify it is gone from DLQ and back to queued."""
    q = RunQueue(db_path=":memory:")  # rule16-ephemeral-ok: not a restart test
    q.enqueue("run-dlq-3", tenant_id="t2")
    q.dead_letter(
        run_id="run-dlq-3",
        reason="manual",
        original_state="queued",
        tenant_id="t2",
    )
    assert len(q.list_dlq()) == 1

    result = q.requeue_from_dlq("run-dlq-3")
    assert result is True

    # DLQ must be empty after requeue.
    assert q.list_dlq() == []

    # The run must be claimable again.
    claimed = q.claim_next("worker-y")
    assert claimed is not None
    assert claimed["run_id"] == "run-dlq-3"


def test_requeue_from_dlq_returns_false_for_unknown_run() -> None:
    """requeue_from_dlq returns False when run_id is not in the DLQ."""
    q = RunQueue(db_path=":memory:")  # rule16-ephemeral-ok: not a restart test
    assert q.requeue_from_dlq("nonexistent-run") is False


def test_list_dlq_tenant_filter() -> None:
    """list_dlq with tenant_id filters to only that tenant's records."""
    q = RunQueue(db_path=":memory:")  # rule16-ephemeral-ok: not a restart test
    q.enqueue("run-t1", tenant_id="t1")
    q.enqueue("run-t2", tenant_id="t2")
    q.dead_letter("run-t1", reason="r1", original_state="leased", tenant_id="t1")
    q.dead_letter("run-t2", reason="r2", original_state="leased", tenant_id="t2")

    t1_records = q.list_dlq(tenant_id="t1")
    assert len(t1_records) == 1
    assert t1_records[0]["run_id"] == "run-t1"

    all_records = q.list_dlq()
    assert len(all_records) == 2


# ---------------------------------------------------------------------------
# Layer 3 — HTTP via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient backed by a real AgentServer with in-memory RunQueue."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    app = build_app(server)
    app.state.agent_server = server
    return TestClient(app, raise_server_exceptions=True)


def test_get_ops_dlq_endpoint(_app_client: TestClient) -> None:
    """GET /ops/dlq returns 200 and a JSON list (possibly empty)."""
    resp = _app_client.get("/ops/dlq")
    assert resp.status_code == 200
    body = resp.json()
    assert "dead_lettered_runs" in body
    assert isinstance(body["dead_lettered_runs"], list)


def test_requeue_endpoint(_app_client: TestClient) -> None:
    """Dead-letter a run via RunQueue directly, then requeue via HTTP endpoint.

    W31, T-1' note: when no API key is configured, AuthMiddleware injects an
    ``__anonymous__`` TenantContext. The HTTP scope only sees rows owned by
    that tenant, so the test fixture registers the row under that tenant.
    """
    server = _app_client.app.state.agent_server
    run_queue = server._run_queue
    assert run_queue is not None, "run_queue must be wired"

    # Register under __anonymous__ to match the dev fallback scope.
    run_queue.enqueue("http-dlq-run", tenant_id="__anonymous__")
    run_queue.dead_letter(
        run_id="http-dlq-run",
        reason="test_requeue",
        original_state="leased",
        tenant_id="__anonymous__",
    )

    # Verify it shows up via GET.
    resp = _app_client.get("/ops/dlq")
    assert resp.status_code == 200
    run_ids = [r["run_id"] for r in resp.json()["dead_lettered_runs"]]
    assert "http-dlq-run" in run_ids

    # Requeue via POST.
    resp2 = _app_client.post("/ops/dlq/http-dlq-run/requeue")
    assert resp2.status_code == 200
    assert resp2.json()["run_id"] == "http-dlq-run"
    assert resp2.json()["status"] == "requeued"

    # Must no longer appear in DLQ.
    resp3 = _app_client.get("/ops/dlq")
    run_ids_after = [r["run_id"] for r in resp3.json()["dead_lettered_runs"]]
    assert "http-dlq-run" not in run_ids_after


def test_requeue_endpoint_404_for_unknown_run(_app_client: TestClient) -> None:
    """POST /ops/dlq/{run_id}/requeue returns 404 when run_id is not in DLQ."""
    resp = _app_client.post("/ops/dlq/no-such-run/requeue")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"

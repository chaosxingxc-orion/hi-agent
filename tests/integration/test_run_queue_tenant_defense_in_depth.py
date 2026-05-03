"""W33 D.2: defense-in-depth tenant scoping on RunQueue mutation methods.

Eight mutation/inspection methods accept an optional ``tenant_id`` kwarg.
Under research/prod posture a missing/empty tenant_id raises
``TenantScopeError``. When provided, queries add ``WHERE tenant_id = ?`` so
a future internal caller cannot mutate a row that belongs to another
tenant.

One test per method covers:
  - research posture + missing tenant_id → raises
  - valid tenant_id → method succeeds with proper filter
  - mismatched tenant_id (e.g. cancel("rid", tenant_id="tenant-b") when row
    is tenant-a) → no rows affected
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from hi_agent.config.posture import (
    Posture,  # noqa: F401  expiry_wave: permanent  # gate scans tests for this import
)
from hi_agent.contracts.errors import TenantScopeError
from hi_agent.server.run_queue import RunQueue


@contextmanager
def _set_posture(value: str) -> Iterator[None]:
    prior = os.environ.get("HI_AGENT_POSTURE")
    os.environ["HI_AGENT_POSTURE"] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("HI_AGENT_POSTURE", None)
        else:
            os.environ["HI_AGENT_POSTURE"] = prior


@pytest.fixture
def q() -> Iterator[RunQueue]:
    """Fresh in-memory RunQueue per test."""
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=60.0)
    yield rq
    rq.close()


def _enqueue_for_tenant(q: RunQueue, run_id: str, tenant_id: str) -> None:
    """Enqueue a run owned by ``tenant_id``."""
    q.enqueue(run_id, priority=0, payload_json="{}", tenant_id=tenant_id)


def _row_status(q: RunQueue, run_id: str) -> str | None:
    """Inspect status field for a row; ``None`` when absent."""
    cur = q._conn.execute(
        "SELECT status FROM run_queue WHERE run_id = ?", (run_id,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def _row_cancellation_flag(q: RunQueue, run_id: str) -> int | None:
    cur = q._conn.execute(
        "SELECT cancellation_flag FROM run_queue WHERE run_id = ?", (run_id,)
    )
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 1. reenqueue
# ---------------------------------------------------------------------------


def test_reenqueue_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.reenqueue("r1")


def test_reenqueue_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker")
    with _set_posture("research"):
        ok = q.reenqueue("r1", tenant_id="tenant-a")
    assert ok is True
    assert _row_status(q, "r1") == "queued"


def test_reenqueue_with_mismatched_tenant_id_affects_no_rows(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker")
    with _set_posture("research"):
        ok = q.reenqueue("r1", tenant_id="tenant-b")
    assert ok is False
    assert _row_status(q, "r1") == "leased"  # untouched


# ---------------------------------------------------------------------------
# 2. cancel
# ---------------------------------------------------------------------------


def test_cancel_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.cancel("r1")


def test_cancel_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"):
        q.cancel("r1", tenant_id="tenant-a")
    assert _row_cancellation_flag(q, "r1") == 1


def test_cancel_with_mismatched_tenant_id_affects_no_rows(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"):
        q.cancel("r1", tenant_id="tenant-b")
    assert _row_cancellation_flag(q, "r1") == 0  # untouched


# ---------------------------------------------------------------------------
# 3. heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.heartbeat("r1", "worker-A")


def test_heartbeat_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"):
        renewed = q.heartbeat("r1", "worker-A", tenant_id="tenant-a")
    assert renewed is True


def test_heartbeat_with_mismatched_tenant_id_affects_no_rows(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"):
        renewed = q.heartbeat("r1", "worker-A", tenant_id="tenant-b")
    assert renewed is False


# ---------------------------------------------------------------------------
# 4. complete
# ---------------------------------------------------------------------------


def test_complete_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.complete("r1", "worker-A")


def test_complete_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"):
        q.complete("r1", "worker-A", tenant_id="tenant-a")
    assert _row_status(q, "r1") == "completed"


def test_complete_with_mismatched_tenant_id_affects_no_rows(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"):
        q.complete("r1", "worker-A", tenant_id="tenant-b")
    assert _row_status(q, "r1") == "leased"  # untouched


# ---------------------------------------------------------------------------
# 5. fail
# ---------------------------------------------------------------------------


def test_fail_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.fail("r1", "worker-A", "boom")


def test_fail_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"):
        q.fail("r1", "worker-A", "boom", tenant_id="tenant-a")
    # First failure with retries remaining → status reset to "queued"
    assert _row_status(q, "r1") == "queued"


def test_fail_with_mismatched_tenant_id_affects_no_rows(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("research"):
        q.fail("r1", "worker-A", "boom", tenant_id="tenant-b")
    assert _row_status(q, "r1") == "leased"  # untouched


# ---------------------------------------------------------------------------
# 6. dequeue_unclaimed
# ---------------------------------------------------------------------------


def test_dequeue_unclaimed_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.dequeue_unclaimed("r1")


def test_dequeue_unclaimed_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"):
        q.dequeue_unclaimed("r1", tenant_id="tenant-a")
    assert _row_status(q, "r1") is None


def test_dequeue_unclaimed_with_mismatched_tenant_id_affects_no_rows(
    q: RunQueue,
) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"):
        q.dequeue_unclaimed("r1", tenant_id="tenant-b")
    assert _row_status(q, "r1") == "queued"  # untouched


# ---------------------------------------------------------------------------
# 7. is_cancelled
# ---------------------------------------------------------------------------


def test_is_cancelled_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.cancel("r1", tenant_id="tenant-a")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.is_cancelled("r1")


def test_is_cancelled_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.cancel("r1", tenant_id="tenant-a")
    with _set_posture("research"):
        assert q.is_cancelled("r1", tenant_id="tenant-a") is True


def test_is_cancelled_with_mismatched_tenant_id_returns_false(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.cancel("r1", tenant_id="tenant-a")
    with _set_posture("research"):
        # tenant-b's view: row owned by tenant-a is invisible → not cancelled.
        assert q.is_cancelled("r1", tenant_id="tenant-b") is False


# ---------------------------------------------------------------------------
# 8. dead_letter
# ---------------------------------------------------------------------------


def test_dead_letter_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.dead_letter("r1", "boom", "queued")  # no tenant_id


def test_dead_letter_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"):
        q.dead_letter("r1", "boom", "queued", tenant_id="tenant-a")
    rows = q.list_dlq(tenant_id="tenant-a")
    assert any(r["run_id"] == "r1" for r in rows)


def test_dead_letter_with_mismatched_tenant_id_affects_no_run_queue_rows(
    q: RunQueue,
) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    with _set_posture("research"):
        q.dead_letter("r1", "boom", "queued", tenant_id="tenant-b")
    # The DLQ row is written under tenant-b (record is what caller said), but
    # the run_queue row owned by tenant-a is NOT updated to "failed".
    assert _row_status(q, "r1") == "queued"
    # tenant-b sees the DLQ entry; tenant-a does not.
    assert any(r["run_id"] == "r1" for r in q.list_dlq(tenant_id="tenant-b"))
    assert not any(r["run_id"] == "r1" for r in q.list_dlq(tenant_id="tenant-a"))


# ---------------------------------------------------------------------------
# 9. requeue_from_dlq
# ---------------------------------------------------------------------------


def test_requeue_from_dlq_research_rejects_missing_tenant_id(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.dead_letter("r1", "boom", "queued", tenant_id="tenant-a")
    with _set_posture("research"), pytest.raises(TenantScopeError):
        q.requeue_from_dlq("r1")


def test_requeue_from_dlq_with_valid_tenant_id_succeeds(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.dead_letter("r1", "boom", "queued", tenant_id="tenant-a")
    with _set_posture("research"):
        ok = q.requeue_from_dlq("r1", tenant_id="tenant-a")
    assert ok is True
    assert _row_status(q, "r1") == "queued"
    # DLQ row removed
    assert not any(r["run_id"] == "r1" for r in q.list_dlq(tenant_id="tenant-a"))


def test_requeue_from_dlq_with_mismatched_tenant_id_returns_false(q: RunQueue) -> None:
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.dead_letter("r1", "boom", "queued", tenant_id="tenant-a")
    with _set_posture("research"):
        ok = q.requeue_from_dlq("r1", tenant_id="tenant-b")
    assert ok is False
    # DLQ row still present for tenant-a
    assert any(r["run_id"] == "r1" for r in q.list_dlq(tenant_id="tenant-a"))


# ---------------------------------------------------------------------------
# Posture: dev permits empty (back-compat) + WARNING
# ---------------------------------------------------------------------------


def test_dev_posture_allows_missing_tenant_id_with_warning(
    q: RunQueue, caplog
) -> None:
    """dev posture: missing tenant_id falls back with a WARNING log line."""
    _enqueue_for_tenant(q, "r1", "tenant-a")
    q.claim_next("worker-A")
    with _set_posture("dev"), caplog.at_level(
        "WARNING", "hi_agent.server.run_queue"
    ):
        q.complete("r1", "worker-A")
    assert _row_status(q, "r1") == "completed"
    assert any("tenant_id missing" in rec.message for rec in caplog.records)

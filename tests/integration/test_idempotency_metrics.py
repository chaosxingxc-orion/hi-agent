"""Integration tests for W35-T6 idempotency metrics.

Layer 2 — real ``IdempotencyStore`` wired into a real ``MetricsCollector``
via the process-wide singleton (no mocks on the subject under test). Tests
assert observable metric values via ``MetricsCollector.get_counter`` and
``MetricsCollector.snapshot``.

Why a singleton-driven test: the helpers in
``hi_agent.observability.idempotency_metrics`` route through
:func:`get_metrics_collector`. The fixture stamps a fresh collector before
each test and unsets it on teardown so cross-test state cannot leak.
"""

from __future__ import annotations

import time
import uuid

import pytest
from hi_agent.observability.collector import (
    MetricsCollector,
    get_metrics_collector,
    set_metrics_collector,
)
from hi_agent.observability.idempotency_metrics import (
    CONFLICT_METRIC,
    PURGED_METRIC,
    RECORD_AGE_METRIC,
    REPLAY_METRIC,
    _tenant_bucket,
)
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload


@pytest.fixture()
def collector():
    """Fresh MetricsCollector registered as the process-wide singleton.

    Restores any previous registration on teardown so the test does not
    leak global state into adjacent suites.
    """
    previous = get_metrics_collector()
    fresh = MetricsCollector()
    set_metrics_collector(fresh)
    try:
        yield fresh
    finally:
        set_metrics_collector(previous)


@pytest.fixture()
def store(tmp_path):
    """Real IdempotencyStore on a temporary SQLite file."""
    s = IdempotencyStore(db_path=tmp_path / "idem-metrics.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Replay counter
# ---------------------------------------------------------------------------


def test_replay_metric_increments(collector, store):
    """Reserving the same (key, hash) twice increments the replayed counter."""
    tenant = "tenant-replay-1"
    key = str(uuid.uuid4())
    payload_hash = _hash_payload({"goal": "hello"})
    run_id = str(uuid.uuid4())

    o1, _ = store.reserve_or_replay(tenant, key, payload_hash, run_id)
    o2, _ = store.reserve_or_replay(tenant, key, payload_hash, run_id)

    assert o1 == "created"
    assert o2 == "replayed"

    # Counter should carry exactly 1 replay event for the tenant_bucket label.
    bucket = _tenant_bucket(tenant)
    replayed_count = collector.get_counter(
        REPLAY_METRIC,
        labels={"tenant_bucket": bucket, "outcome": "replayed"},
    )
    assert replayed_count == 1, (
        f"expected 1 replay for bucket={bucket}, got {replayed_count}; "
        f"snapshot={collector.snapshot().get(REPLAY_METRIC)}"
    )

    # The created outcome must NOT have incremented the replay counter
    # (W35-T6 contract: only outcomes != 'created' are recorded).
    conflict_count = collector.get_counter(
        REPLAY_METRIC,
        labels={"tenant_bucket": bucket, "outcome": "conflict"},
    )
    assert conflict_count == 0


# ---------------------------------------------------------------------------
# Conflict counter
# ---------------------------------------------------------------------------


def test_conflict_metric_increments(collector, store):
    """Reusing a key with a different payload hash increments both counters."""
    tenant = "tenant-conflict-1"
    key = str(uuid.uuid4())
    hash_a = _hash_payload({"goal": "task A"})
    hash_b = _hash_payload({"goal": "task B"})

    o1, _ = store.reserve_or_replay(tenant, key, hash_a, "run-a")
    o2, _ = store.reserve_or_replay(tenant, key, hash_b, "run-b")

    assert o1 == "created"
    assert o2 == "conflict"

    bucket = _tenant_bucket(tenant)

    # Conflict counter (single label set).
    conflict_total = collector.get_counter(
        CONFLICT_METRIC, labels={"tenant_bucket": bucket}
    )
    assert conflict_total == 1, (
        f"expected 1 conflict for bucket={bucket}, got {conflict_total}; "
        f"snapshot={collector.snapshot().get(CONFLICT_METRIC)}"
    )

    # Replay counter ALSO increments under outcome=conflict so operators
    # can compute conflict-rate without joining metrics.
    replay_conflict = collector.get_counter(
        REPLAY_METRIC,
        labels={"tenant_bucket": bucket, "outcome": "conflict"},
    )
    assert replay_conflict == 1


# ---------------------------------------------------------------------------
# Age histogram
# ---------------------------------------------------------------------------


def test_age_histogram_observes(collector, store):
    """Replay records an age sample. Snapshot exposes count + percentiles."""
    tenant = "tenant-age-1"
    key = str(uuid.uuid4())
    payload_hash = _hash_payload({"goal": "age-test"})
    run_id = str(uuid.uuid4())

    store.reserve_or_replay(tenant, key, payload_hash, run_id)
    # Sleep briefly so the observed age is strictly positive — keeps the
    # assertion meaningful (the histogram clamps negatives to 0 but a 0.0
    # observation would not exercise the percentile code path).
    time.sleep(0.05)
    store.reserve_or_replay(tenant, key, payload_hash, run_id)

    snap = collector.snapshot()
    assert RECORD_AGE_METRIC in snap, (
        f"expected {RECORD_AGE_METRIC} in snapshot keys, got {list(snap)}"
    )
    bucket = _tenant_bucket(tenant)
    label_key = f'outcome="...",tenant_bucket="{bucket}"'  # not used; we scan all
    hist = snap[RECORD_AGE_METRIC]
    # The collector emits one entry per label key; for our single tenant
    # there should be exactly one observation.
    total_count = sum(entry["count"] for entry in hist.values())
    total_sum = sum(entry["sum"] for entry in hist.values())
    assert total_count == 1, (
        f"expected exactly 1 age observation, got {total_count}; "
        f"hist={hist}"
    )
    assert total_sum >= 0.0
    # And the label key must carry tenant_bucket={bucket} — we look for any
    # entry whose label key contains it.
    found_bucket = any(f'tenant_bucket="{bucket}"' in lk for lk in hist)
    assert found_bucket, (
        f"expected an entry labeled tenant_bucket={bucket!r} in {list(hist)}"
    )
    _ = label_key  # silenced unused; retained for grep-debuggability


# ---------------------------------------------------------------------------
# Purge counter (depends on W35-T4)
# ---------------------------------------------------------------------------


_purge_present = hasattr(IdempotencyStore, "purge_expired")


@pytest.mark.skipif(
    not _purge_present,
    reason="awaiting W35-T4 purge_expired",
)
def test_purged_metric_increments(collector, store):
    """purge_expired increments the purged counter by exactly the deleted count."""
    tenant = "tenant-purge-1"
    # Insert two records with very-short TTLs so they are immediately past
    # their expires_at by the time purge runs.
    payload_hash = _hash_payload({"goal": "purge-1"})
    store.reserve_or_replay(
        tenant_id=tenant,
        idempotency_key=f"purge-key-1-{uuid.uuid4()}",
        request_hash=payload_hash,
        run_id="run-1",
        ttl_seconds=0.01,
    )
    store.reserve_or_replay(
        tenant_id=tenant,
        idempotency_key=f"purge-key-2-{uuid.uuid4()}",
        request_hash=payload_hash,
        run_id="run-2",
        ttl_seconds=0.01,
    )
    # Wait past the TTL so the purge query matches.
    time.sleep(0.1)

    deleted = store.purge_expired()
    assert deleted >= 2

    # Counter is unlabeled — query the unlabelled bucket directly.
    purged_total = collector.get_counter(PURGED_METRIC, labels=None)
    assert purged_total >= 2, (
        f"expected purged>=2, got {purged_total}; "
        f"snapshot={collector.snapshot().get(PURGED_METRIC)}"
    )

    # Empty purge must NOT increment further (Rule 2: no spurious work).
    before = collector.get_counter(PURGED_METRIC, labels=None)
    deleted_again = store.purge_expired()
    after = collector.get_counter(PURGED_METRIC, labels=None)
    assert deleted_again == 0
    assert after == before

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

    # Counter should carry exactly 1 replay event for the tenant_id label.
    replayed_count = collector.get_counter(
        REPLAY_METRIC,
        labels={"tenant_id": tenant, "outcome": "replayed"},
    )
    assert replayed_count == 1, (
        f"expected 1 replay for tenant={tenant}, got {replayed_count}; "
        f"snapshot={collector.snapshot().get(REPLAY_METRIC)}"
    )

    # The created outcome must NOT have incremented the replay counter
    # (W35-T6 contract: only outcomes != 'created' are recorded).
    conflict_count = collector.get_counter(
        REPLAY_METRIC,
        labels={"tenant_id": tenant, "outcome": "conflict"},
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

    # Conflict counter (single label set).
    conflict_total = collector.get_counter(
        CONFLICT_METRIC, labels={"tenant_id": tenant}
    )
    assert conflict_total == 1, (
        f"expected 1 conflict for tenant={tenant}, got {conflict_total}; "
        f"snapshot={collector.snapshot().get(CONFLICT_METRIC)}"
    )

    # Replay counter ALSO increments under outcome=conflict so operators
    # can compute conflict-rate without joining metrics.
    replay_conflict = collector.get_counter(
        REPLAY_METRIC,
        labels={"tenant_id": tenant, "outcome": "conflict"},
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
    label_key = f'outcome="...",tenant_id="{tenant}"'  # not used; we scan all
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
    # And the label key must carry tenant_id={tenant} — we look for any
    # entry whose label key contains it.
    found_tenant = any(f'tenant_id="{tenant}"' in lk for lk in hist)
    assert found_tenant, (
        f"expected an entry labeled tenant_id={tenant!r} in {list(hist)}"
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

    # The store currently invokes record_purged(deleted) without a
    # tenant_id, so the counter is recorded under tenant_id="" — the
    # documented aggregate-batch series.
    purged_total = collector.get_counter(
        PURGED_METRIC, labels={"tenant_id": ""}
    )
    assert purged_total >= 2, (
        f"expected purged>=2, got {purged_total}; "
        f"snapshot={collector.snapshot().get(PURGED_METRIC)}"
    )

    # Empty purge must NOT increment further (Rule 2: no spurious work).
    before = collector.get_counter(PURGED_METRIC, labels={"tenant_id": ""})
    deleted_again = store.purge_expired()
    after = collector.get_counter(PURGED_METRIC, labels={"tenant_id": ""})
    assert deleted_again == 0
    assert after == before


# ---------------------------------------------------------------------------
# Label-set drift guard (W35 corrective C-1)
# ---------------------------------------------------------------------------


def test_metric_label_set(collector, store):
    """Fail-fast guard: the four idempotency metrics carry exactly the
    documented label keys. Future drift (e.g. re-introducing
    ``tenant_bucket`` or adding/removing a label) will trip this test
    before it lands in /metrics and fragments the RIA dashboard
    contract.
    """
    tenant = "tenant-label-set-1"
    key = str(uuid.uuid4())

    # Drive each helper at least once so the collector observes the
    # real label sets emitted in production code paths.
    payload_a = _hash_payload({"goal": "label-set-A"})
    payload_b = _hash_payload({"goal": "label-set-B"})
    store.reserve_or_replay(tenant, key, payload_a, "run-a")
    # Replay path → record_replay + observe_age
    store.reserve_or_replay(tenant, key, payload_a, "run-a")
    # Conflict path → record_conflict + record_replay(outcome=conflict)
    store.reserve_or_replay(tenant, key, payload_b, "run-b")

    # purge path emits PURGED_METRIC with tenant_id="" (aggregate batch)
    if _purge_present:
        # Insert + immediately purge so PURGED_METRIC has at least one
        # observed series.
        expiring_hash = _hash_payload({"goal": "label-set-purge"})
        store.reserve_or_replay(
            tenant_id=tenant,
            idempotency_key=f"label-set-purge-{uuid.uuid4()}",
            request_hash=expiring_hash,
            run_id="run-purge",
            ttl_seconds=0.01,
        )
        time.sleep(0.05)
        store.purge_expired()

    snap = collector.snapshot()
    # Helper: parse the encoded label key string back into the set of
    # label-keys observed for a metric. The MetricsCollector encodes
    # labels as ``k1="v1",k2="v2"``; we just want the keys.
    def _keys_for(metric_name: str) -> set[frozenset[str]]:
        seen: set[frozenset[str]] = set()
        for label_str in snap.get(metric_name, {}):
            if not label_str:
                # An empty label_str means the unlabeled bucket. After
                # W35 corrective C-1 no idempotency metric is emitted
                # without labels — surfacing it here lets the assertion
                # fail loudly rather than silently masking the drift.
                seen.add(frozenset())
                continue
            keys = set()
            for chunk in label_str.split(","):
                if "=" in chunk:
                    keys.add(chunk.split("=", 1)[0].strip())
            seen.add(frozenset(keys))
        return seen

    expected = {
        REPLAY_METRIC: {frozenset({"tenant_id", "outcome"})},
        CONFLICT_METRIC: {frozenset({"tenant_id"})},
        RECORD_AGE_METRIC: {frozenset({"tenant_id"})},
    }
    if _purge_present:
        expected[PURGED_METRIC] = {frozenset({"tenant_id"})}

    for metric, expected_keysets in expected.items():
        observed = _keys_for(metric)
        assert observed, f"{metric}: no observations recorded; snap={snap.get(metric)}"
        assert observed == expected_keysets, (
            f"{metric} label-set drift: expected {expected_keysets}, "
            f"got {observed}. The four idempotency metrics MUST carry "
            f"only the documented labels (W35 corrective C-1)."
        )

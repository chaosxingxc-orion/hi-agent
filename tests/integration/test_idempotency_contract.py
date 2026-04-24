"""Integration test: idempotency contract for POST /runs.

Scenario: same Idempotency-Key + same body submitted 3 times.
Expected: 1 created + 2 replayed; run_id identical across all three.
"""
from __future__ import annotations

import uuid

import pytest
from hi_agent.server.idempotency import (
    IdempotencyStore,
    _hash_payload,
)


@pytest.fixture()
def idem_store(tmp_path):
    return IdempotencyStore(db_path=tmp_path / "idem.db")


def test_same_key_same_payload_replayed(idem_store):
    """Three requests with identical key+payload return created then replayed."""
    tenant = "t1"
    key = str(uuid.uuid4())
    payload = {"goal": "hello", "profile_id": "proj1"}
    payload_hash = _hash_payload(payload)
    run_id = str(uuid.uuid4())

    o1, r1 = idem_store.reserve_or_replay(tenant, key, payload_hash, run_id)
    o2, r2 = idem_store.reserve_or_replay(tenant, key, payload_hash, run_id)
    o3, r3 = idem_store.reserve_or_replay(tenant, key, payload_hash, run_id)

    assert o1 == "created"
    assert o2 == "replayed"
    assert o3 == "replayed"
    assert r1.run_id == r2.run_id == r3.run_id == run_id


def test_same_key_different_payload_conflict(idem_store):
    """Same key with a different body hash returns 'conflict'."""
    tenant = "t1"
    key = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    hash_a = _hash_payload({"goal": "task A"})
    hash_b = _hash_payload({"goal": "task B"})

    outcome_a, _ = idem_store.reserve_or_replay(tenant, key, hash_a, run_id)
    outcome_b, _ = idem_store.reserve_or_replay(tenant, key, hash_b, run_id)

    assert outcome_a == "created"
    assert outcome_b == "conflict"


def test_different_keys_independent(idem_store):
    """Different idempotency keys create independent records."""
    tenant = "t1"
    key_a = str(uuid.uuid4())
    key_b = str(uuid.uuid4())
    h = _hash_payload({"goal": "same goal"})

    o_a, r_a = idem_store.reserve_or_replay(tenant, key_a, h, "run-a")
    o_b, r_b = idem_store.reserve_or_replay(tenant, key_b, h, "run-b")

    assert o_a == "created"
    assert o_b == "created"
    assert r_a.run_id != r_b.run_id


def test_tenant_isolation(idem_store):
    """Same key across different tenants creates independent records."""
    key = str(uuid.uuid4())
    h = _hash_payload({"goal": "goal"})

    o_t1, r_t1 = idem_store.reserve_or_replay("tenant_1", key, h, "run-t1")
    o_t2, r_t2 = idem_store.reserve_or_replay("tenant_2", key, h, "run-t2")

    assert o_t1 == "created"
    assert o_t2 == "created"
    assert r_t1.run_id != r_t2.run_id


def test_replay_returns_original_run_id(idem_store):
    """Replayed request returns the original run_id, not the caller-supplied one."""
    tenant = "t1"
    key = str(uuid.uuid4())
    h = _hash_payload({"goal": "g"})
    original_run_id = "original-run-id"
    retry_run_id = "retry-run-id"  # different but shouldn't matter

    _, r_created = idem_store.reserve_or_replay(tenant, key, h, original_run_id)
    _, r_replayed = idem_store.reserve_or_replay(tenant, key, h, retry_run_id)

    assert r_created.run_id == original_run_id
    assert r_replayed.run_id == original_run_id

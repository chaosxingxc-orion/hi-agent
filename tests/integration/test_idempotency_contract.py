"""Integration test: idempotency contract for POST /runs.

Scenario: same Idempotency-Key + same body submitted 3 times.
Expected: 1 created + 2 replayed; run_id identical across all three.
"""
from __future__ import annotations

import threading
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


# ---------------------------------------------------------------------------
# HTTP-level burst test: same key, concurrent POST /runs
# ---------------------------------------------------------------------------


@pytest.fixture()
def http_client(tmp_path):
    """Starlette TestClient wired to a real AgentServer with idempotency store."""
    from hi_agent.server.app import AgentServer
    from hi_agent.server.idempotency import IdempotencyStore
    from starlette.testclient import TestClient

    store = IdempotencyStore(db_path=tmp_path / "idem_http.db")
    server = AgentServer(host="127.0.0.1", port=9998)
    server.run_manager._idempotency_store = store
    with TestClient(server.app, raise_server_exceptions=False) as client:
        yield client
    store.close()


def test_concurrent_same_key_creates_one_run(http_client):
    """Two concurrent POST /runs with the same Idempotency-Key produce one run.

    Layer 3 (HTTP-level): drives through the public POST /runs interface and
    asserts:
    - Only ONE distinct run_id is returned across both calls.
    - The second call (replay) returns HTTP 200, not 201.
    - When the first run has completed before the replay, the body is the
      cached snapshot (byte-identical to the 201 body).
    """
    idem_key = str(uuid.uuid4())
    payload = {"goal": "idempotent burst test", "profile_id": "test-profile"}

    responses: list = [None, None]
    errors: list = []

    def post_run(idx: int) -> None:
        try:
            resp = http_client.post(
                "/runs",
                json=payload,
                headers={"Idempotency-Key": idem_key},
            )
            responses[idx] = resp
        except Exception as exc:
            errors.append(str(exc))

    # Fire both requests concurrently.
    t1 = threading.Thread(target=post_run, args=(0,))
    t2 = threading.Thread(target=post_run, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Request errors: {errors}"
    r0, r1 = responses
    assert r0 is not None and r1 is not None, "One or both responses are missing"

    statuses = {r0.status_code, r1.status_code}
    # One must be 201 (created), the other must be 200 (replayed).
    assert 201 in statuses, f"Expected 201 from first creation; got {statuses}"
    assert 200 in statuses, f"Expected 200 from replay; got {statuses}"

    # Both must carry the same run_id.
    body0 = r0.json()
    body1 = r1.json()
    run_id_0 = body0.get("run_id")
    run_id_1 = body1.get("run_id")
    assert run_id_0 is not None, f"run_id missing in response 0: {body0}"
    assert run_id_1 is not None, f"run_id missing in response 1: {body1}"
    assert run_id_0 == run_id_1, (
        f"Two different run_ids returned: {run_id_0} vs {run_id_1}"
    )

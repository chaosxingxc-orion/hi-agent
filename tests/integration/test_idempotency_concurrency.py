"""Integration tests for RO-9: idempotency reserve is atomic under concurrent submit.

Uses ThreadPoolExecutor to submit 5 concurrent requests with the same
idempotency key and verifies that exactly one "created" outcome is returned
(all others are "replayed" or "conflict" — not a second "created").

Layer 2 — Integration: real IdempotencyStore + real RunManager.
Zero MagicMock on the subsystem under test.
"""
from __future__ import annotations

import concurrent.futures
import threading

import pytest
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload
from hi_agent.server.run_manager import RunManager
from hi_agent.server.tenant_context import TenantContext


@pytest.fixture()
def store(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "idempotency.db")
    yield s
    s.close()


@pytest.fixture()
def manager(store):
    rm = RunManager(idempotency_store=store)
    yield rm
    rm.shutdown()


class TestIdempotencyConcurrentReserve:
    """RO-9: atomic INSERT + catch IntegrityError prevents duplicate creation."""

    def test_five_concurrent_submits_create_exactly_one_run(self, store):
        """5 concurrent calls to reserve_or_replay with the same tenant/key
        must produce exactly 1 'created' outcome and 4 'replayed' outcomes."""
        tenant = "tenant-concurrency"
        key = "concurrent-idem-key-001"
        request_hash = _hash_payload({"goal": "concurrent task"})

        results: list[tuple[str, str]] = []  # (outcome, run_id)
        barrier = threading.Barrier(5)

        def _submit(i: int):
            barrier.wait()  # synchronize all threads to maximize contention
            outcome, record = store.reserve_or_replay(
                tenant_id=tenant,
                idempotency_key=key,
                request_hash=request_hash,
                run_id=f"run-concurrent-{i:02d}",
            )
            return outcome, record.run_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_submit, i) for i in range(5)]
            for f in concurrent.futures.as_completed(futures):
                outcome, run_id = f.result()
                results.append((outcome, run_id))

        outcomes = [r[0] for r in results]
        created_count = outcomes.count("created")
        replayed_count = outcomes.count("replayed")

        assert created_count == 1, (
            f"Expected exactly 1 'created' outcome, got {created_count}. "
            f"All outcomes: {outcomes}"
        )
        assert replayed_count == 4, (
            f"Expected 4 'replayed' outcomes, got {replayed_count}. "
            f"All outcomes: {outcomes}"
        )

        # All replayed records must point to the same run_id as the created one.
        created_run_id = next(run_id for outcome, run_id in results if outcome == "created")
        replayed_run_ids = {run_id for outcome, run_id in results if outcome == "replayed"}
        assert replayed_run_ids == {created_run_id}, (
            f"Replayed run_ids {replayed_run_ids!r} must all match created "
            f"run_id {created_run_id!r}"
        )

    def test_five_concurrent_submits_via_run_manager(self, manager):
        """5 concurrent create_run calls with the same idempotency_key must
        produce exactly 1 run in the registry."""
        workspace = TenantContext(tenant_id="tenant-conc-mgr", user_id="user-1")
        payload = {"goal": "concurrent task", "idempotency_key": "concurrent-mgr-key-001"}

        run_ids: list[str] = []
        outcomes: list[str] = []
        barrier = threading.Barrier(5)

        def _submit(_i: int):
            barrier.wait()
            run = manager.create_run(dict(payload), workspace=workspace)
            return run.run_id, run.outcome

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_submit, i) for i in range(5)]
            for f in concurrent.futures.as_completed(futures):
                run_id, outcome = f.result()
                run_ids.append(run_id)
                outcomes.append(outcome)

        # Exactly 1 "created"; the rest must be "replayed".
        created = outcomes.count("created")
        replayed = outcomes.count("replayed")
        assert created == 1, f"Expected 1 created, got {created}. outcomes={outcomes}"
        assert replayed == 4, f"Expected 4 replayed, got {replayed}. outcomes={outcomes}"

        # All run IDs should be the same (the original run).
        unique_run_ids = set(run_ids)
        assert len(unique_run_ids) == 1, (
            f"All submissions should refer to the same run_id, got: {unique_run_ids}"
        )

    def test_different_tenants_do_not_block_each_other(self, store):
        """Concurrent submits from different tenants with the same key
        each succeed as 'created' (no cross-tenant collision)."""
        key = "shared-key-multi-tenant"
        request_hash = _hash_payload({"goal": "multi-tenant task"})

        results: list[tuple[str, str, str]] = []  # (tenant, outcome, run_id)

        def _submit(tenant_id: str, run_id: str):
            outcome, record = store.reserve_or_replay(
                tenant_id=tenant_id,
                idempotency_key=key,
                request_hash=request_hash,
                run_id=run_id,
            )
            return tenant_id, outcome, record.run_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(_submit, f"tenant-{i}", f"run-{i:02d}")
                for i in range(4)
            ]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        # Each tenant must have exactly 1 'created' outcome.
        tenant_outcomes: dict[str, list[str]] = {}
        for tenant, outcome, _ in results:
            tenant_outcomes.setdefault(tenant, []).append(outcome)

        for tenant, tenant_result_list in tenant_outcomes.items():
            assert tenant_result_list == ["created"], (
                f"Tenant {tenant!r} expected ['created'], got {tenant_result_list}"
            )

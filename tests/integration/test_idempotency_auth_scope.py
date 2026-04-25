"""Integration tests for RO-1: IdempotencyStore derives tenant from authenticated
TenantContext, not the request body.

Layer 2 — Integration: real IdempotencyStore + real RunManager wired together.
Zero mocks on the subsystem under test.
"""
from __future__ import annotations

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


class TestAuthScopeIsolation:
    """RO-1: two tenants with the same body tenant_id but different auth tenants
    must produce separate idempotency slots, not collide."""

    def test_same_body_tenant_different_auth_tenant_creates_two_records(self, manager):
        """Tenant A and Tenant B each submit with the same body tenant_id='shared'
        and the same idempotency_key.  Because RunManager now uses workspace.tenant_id
        (the authenticated identity), both creates succeed separately."""
        payload_a = {
            "goal": "do thing A",
            "tenant_id": "shared",  # body-supplied — MUST be ignored
            "idempotency_key": "idem-key-001",
        }
        payload_b = dict(payload_a)  # same body, different auth context

        workspace_a = TenantContext(tenant_id="auth-tenant-A", user_id="user-a")
        workspace_b = TenantContext(tenant_id="auth-tenant-B", user_id="user-b")

        run_a = manager.create_run(payload_a, workspace=workspace_a)
        run_b = manager.create_run(payload_b, workspace=workspace_b)

        # Different auth tenants → different idempotency slots → different run IDs.
        assert run_a.outcome == "created"
        assert run_b.outcome == "created"
        assert run_a.run_id != run_b.run_id

    def test_same_auth_tenant_same_key_same_payload_returns_replayed(self, manager):
        """Same authenticated tenant with the same key + payload → replay."""
        payload = {"goal": "analyse", "idempotency_key": "idem-key-002"}
        workspace = TenantContext(tenant_id="auth-tenant-X", user_id="user-x")

        run1 = manager.create_run(payload, workspace=workspace)
        run2 = manager.create_run(payload, workspace=workspace)

        assert run1.outcome == "created"
        assert run2.outcome == "replayed"
        assert run2.run_id == run1.run_id

    def test_tenant_id_from_body_is_not_used_for_idempotency_key(self, store):
        """Directly verify that reserve_or_replay uses authenticated tenant_id
        by checking that body-supplied tenant_id='forged' does NOT match auth tenant."""
        real_tenant = "real-tenant"
        forged_tenant = "forged-tenant"
        key = "idem-key-forgery"
        payload = {"goal": "x"}
        request_hash = _hash_payload(payload)

        # Reserve under real tenant.
        outcome1, record1 = store.reserve_or_replay(
            tenant_id=real_tenant,
            idempotency_key=key,
            request_hash=request_hash,
            run_id="run-real",
        )
        assert outcome1 == "created"

        # Same key, but different (forged) tenant → new slot, not a replay.
        outcome2, record2 = store.reserve_or_replay(
            tenant_id=forged_tenant,
            idempotency_key=key,
            request_hash=request_hash,
            run_id="run-forged",
        )
        assert outcome2 == "created"
        assert record2.run_id == "run-forged"
        assert record1.run_id != record2.run_id

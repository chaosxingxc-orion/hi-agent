"""Unit tests for OpsSnapshotStore tenant scoping (W32 Track B, Gap 2).

The OpsSnapshotStore is keyed by ``(tenant_id, run_id)`` so two tenants
issuing the same run_id never observe each other's snapshots. Pre-W32 the
store filtered solely by ``run_id`` — a cross-tenant collision risk.

Layer 1 — Unit: pure OpsSnapshotStore, no real dependencies.
"""

from __future__ import annotations

import pytest
from hi_agent.management.ops_snapshot_store import OpsSnapshotStore


class TestTenantScopedFiltering:
    """latest/list_run filter by ``(tenant_id, run_id)``."""

    def test_latest_does_not_leak_across_tenants_with_same_run_id(self) -> None:
        """Two tenants with same run_id observe only their own snapshot."""
        store = OpsSnapshotStore()
        store.append(
            {"run_id": "run-collide", "tenant_id": "t-a", "timestamp": 10.0, "status": "alpha"}
        )
        store.append(
            {"run_id": "run-collide", "tenant_id": "t-b", "timestamp": 20.0, "status": "bravo"}
        )

        latest_a = store.latest("run-collide", "t-a")
        latest_b = store.latest("run-collide", "t-b")

        assert latest_a is not None
        assert latest_a["status"] == "alpha"
        assert latest_a["tenant_id"] == "t-a"

        assert latest_b is not None
        assert latest_b["status"] == "bravo"
        assert latest_b["tenant_id"] == "t-b"

    def test_list_run_does_not_leak_across_tenants_with_same_run_id(self) -> None:
        """list_run returns only the calling tenant's snapshots."""
        store = OpsSnapshotStore()
        store.append({"run_id": "run-X", "tenant_id": "t-a", "timestamp": 1.0})
        store.append({"run_id": "run-X", "tenant_id": "t-a", "timestamp": 2.0})
        store.append({"run_id": "run-X", "tenant_id": "t-b", "timestamp": 3.0})
        store.append({"run_id": "run-X", "tenant_id": "t-b", "timestamp": 4.0})

        items_a = store.list_run("run-X", "t-a")
        items_b = store.list_run("run-X", "t-b")

        assert [item["timestamp"] for item in items_a] == [1.0, 2.0]
        assert all(item["tenant_id"] == "t-a" for item in items_a)
        assert [item["timestamp"] for item in items_b] == [3.0, 4.0]
        assert all(item["tenant_id"] == "t-b" for item in items_b)

    def test_latest_returns_none_when_run_belongs_to_other_tenant(self) -> None:
        """A run_id appended under one tenant is invisible to another."""
        store = OpsSnapshotStore()
        store.append({"run_id": "run-Y", "tenant_id": "t-a", "timestamp": 1.0})

        # Tenant B asks about run-Y — must see nothing.
        assert store.latest("run-Y", "t-b") is None
        assert store.list_run("run-Y", "t-b") == []

    def test_append_requires_tenant_id(self) -> None:
        """append() rejects snapshots missing or carrying empty tenant_id."""
        store = OpsSnapshotStore()
        with pytest.raises(ValueError, match="tenant_id"):
            store.append({"run_id": "run-1", "timestamp": 1.0})
        with pytest.raises(ValueError, match="tenant_id"):
            store.append({"run_id": "run-1", "tenant_id": "", "timestamp": 1.0})
        with pytest.raises(ValueError, match="tenant_id"):
            store.append({"run_id": "run-1", "tenant_id": "   ", "timestamp": 1.0})

    def test_latest_requires_tenant_id(self) -> None:
        """latest() rejects empty tenant_id to prevent silent unscoped reads."""
        store = OpsSnapshotStore()
        store.append({"run_id": "run-1", "tenant_id": "t-a", "timestamp": 1.0})
        with pytest.raises(ValueError, match="tenant_id"):
            store.latest("run-1", "")
        with pytest.raises(ValueError, match="tenant_id"):
            store.latest("run-1", "   ")

    def test_list_run_requires_tenant_id(self) -> None:
        """list_run() rejects empty tenant_id to prevent silent unscoped reads."""
        store = OpsSnapshotStore()
        store.append({"run_id": "run-1", "tenant_id": "t-a", "timestamp": 1.0})
        with pytest.raises(ValueError, match="tenant_id"):
            store.list_run("run-1", "")
        with pytest.raises(ValueError, match="tenant_id"):
            store.list_run("run-1", "   ")

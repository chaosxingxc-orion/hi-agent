"""Integration tests: OpHandle/OpStore/Coordinator posture guards (Wave 10.3 W3-A)."""
from __future__ import annotations

from pathlib import Path

import pytest


class TestLongRunningOpStoreCreatePosture:
    """LongRunningOpStore.create raises under strict posture when tenant_id is empty."""

    def _make_store(self, tmp_path: Path):
        from hi_agent.experiment.op_store import LongRunningOpStore

        return LongRunningOpStore(tmp_path / "ops.db")

    def test_dev_posture_empty_tenant_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        store = self._make_store(tmp_path)
        handle = store.create(
            op_id="op-1",
            backend="test",
            external_id="ext-1",
            submitted_at=0.0,
            tenant_id="",
        )
        assert handle.op_id == "op-1"
        assert handle.tenant_id == ""

    def test_research_posture_empty_tenant_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        store = self._make_store(tmp_path)
        with pytest.raises(ValueError, match="empty tenant_id"):
            store.create(
                op_id="op-2",
                backend="test",
                external_id="ext-2",
                submitted_at=0.0,
                tenant_id="",
            )

    def test_dev_posture_non_empty_tenant_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        store = self._make_store(tmp_path)
        handle = store.create(
            op_id="op-3",
            backend="test",
            external_id="ext-3",
            submitted_at=0.0,
            tenant_id="tenant-abc",
        )
        assert handle.tenant_id == "tenant-abc"


class TestLongRunningOpCoordinatorSubmitPosture:
    """LongRunningOpCoordinator.submit raises under strict posture when tenant_id is empty."""

    def _make_coordinator(self, tmp_path: Path):
        from hi_agent.experiment.coordinator import LongRunningOpCoordinator
        from hi_agent.experiment.op_store import LongRunningOpStore

        store = LongRunningOpStore(tmp_path / "ops.db")
        coord = LongRunningOpCoordinator(store)

        class FakeBackend:
            def submit(self, spec):
                return "ext-" + str(id(spec))

        coord.register_backend("fake", FakeBackend())
        return coord

    def test_dev_posture_non_empty_tenant_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        coord = self._make_coordinator(tmp_path)
        handle = coord.submit(
            op_spec={"task": "x"},
            backend_name="fake",
            tenant_id="tenant-xyz",
        )
        assert handle.tenant_id == "tenant-xyz"

"""Integration: SQLiteGateStore/InMemoryGateAPI unscoped-read posture guards (W10.3 W3-A)."""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_gate_context(gate_ref: str = "gr-1", tenant_id: str = "t1"):
    from hi_agent.management.gate_context import GateContext

    return GateContext(
        gate_ref=gate_ref,
        run_id="r1",
        stage_id="S1",
        branch_id="b1",
        submitter="submitter-1",
        tenant_id=tenant_id,
    )


class TestSQLiteGateStoreUnscoped:
    """SQLiteGateStore.get_gate raises under strict posture when tenant_id=None."""

    def _make_store(self, tmp_path: Path):
        from hi_agent.management.gate_store import SQLiteGateStore

        return SQLiteGateStore(tmp_path / "gates.db")

    def test_research_unscoped_get_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        store = self._make_store(tmp_path)
        with pytest.raises(ValueError, match="strict posture"):
            store.get_gate("nonexistent-ref", tenant_id=None)

    def test_dev_unscoped_get_returns_value_error_for_missing(self, tmp_path, monkeypatch):
        """Under dev, unscoped get emits warning; not found raises ValueError (not posture)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        store = self._make_store(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            store.get_gate("nonexistent-ref", tenant_id=None)

    def test_research_internal_unscoped_does_not_raise_posture_error(
        self, tmp_path, monkeypatch
    ):
        """internal_unscoped=True bypasses posture check; gate not found raises (gate err)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        store = self._make_store(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            store.get_gate("nonexistent-ref", tenant_id=None, internal_unscoped=True)

    def test_dev_scoped_get_with_tenant_works(self, tmp_path, monkeypatch):
        """Scoped tenant_id reads never trigger posture guard in any posture."""
        from hi_agent.management.gate_timeout import GateTimeoutPolicy

        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        store = self._make_store(tmp_path)
        ctx = _make_gate_context("gr-dev-1", tenant_id="t-dev")
        store.create_gate(
            context=ctx,
            timeout_seconds=300.0,
            timeout_policy=GateTimeoutPolicy.REJECT,
        )
        record = store.get_gate("gr-dev-1", tenant_id="t-dev")
        assert record.context.gate_ref == "gr-dev-1"

    def test_research_unscoped_list_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        store = self._make_store(tmp_path)
        with pytest.raises(ValueError, match="strict posture"):
            store.list_pending(tenant_id=None)

    def test_research_internal_unscoped_list_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        store = self._make_store(tmp_path)
        result = store.list_pending(internal_unscoped=True)
        assert isinstance(result, list)


class TestInMemoryGateAPIUnscoped:
    """InMemoryGateAPI mirrors the same posture guard behaviour."""

    def test_research_unscoped_get_raises(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        from hi_agent.management.gate_api import InMemoryGateAPI

        api = InMemoryGateAPI()
        with pytest.raises(ValueError, match="strict posture"):
            api.get_gate("gr-missing", tenant_id=None)

    def test_research_internal_unscoped_get_raises_missing_not_posture(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        from hi_agent.management.gate_api import InMemoryGateAPI

        api = InMemoryGateAPI()
        with pytest.raises(ValueError, match="not found"):
            api.get_gate("gr-missing", tenant_id=None, internal_unscoped=True)

    def test_research_unscoped_list_raises(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        from hi_agent.management.gate_api import InMemoryGateAPI

        api = InMemoryGateAPI()
        with pytest.raises(ValueError, match="strict posture"):
            api.list_pending(tenant_id=None)

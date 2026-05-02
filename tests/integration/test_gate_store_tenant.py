"""W31 T-13' regression: gate_store / gate_api strict-posture refusal pinned.

Pre-W31 the helper that wraps unscoped gate reads warned under all postures
but did not actually raise; this file pins the new contract:

  - Under research/prod posture, ``list_pending()`` and ``get_gate(ref)``
    raise ``ValueError`` when called without ``tenant_id`` (unless the
    caller passes ``internal_unscoped=True`` — reserved for in-process
    callers like ``resolve`` / ``apply_timeouts``).
  - Under dev posture, an unscoped read logs a WARNING and returns the
    cross-tenant pool (legacy compat).

Layer 2 — Integration: real ``SQLiteGateStore`` + ``InMemoryGateAPI``
instances against ``tmp_path``; no mocks on the subsystem under test.
"""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_store import SQLiteGateStore

pytestmark = pytest.mark.integration


def _ctx(gate_ref: str):
    return build_gate_context(
        gate_ref=gate_ref,
        run_id=f"run-{gate_ref}",
        stage_id="s1",
        branch_id="b1",
        submitter="alice",
    )


@pytest.fixture()
def populated_store(tmp_path):
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    store.create_gate(context=_ctx("g-a"), tenant_id="tenant-A")
    store.create_gate(context=_ctx("g-b"), tenant_id="tenant-B")
    yield store
    store.close()


class TestStrictPostureRaisesOnUnscopedReads:
    """Research/prod posture turns unscoped gate reads into hard errors."""

    @pytest.mark.parametrize("posture_name", ["research", "prod"])
    def test_list_pending_raises_under_strict_posture(
        self, populated_store, monkeypatch, posture_name
    ):
        monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
        with pytest.raises(ValueError, match="without tenant_id under strict"):
            populated_store.list_pending()

    @pytest.mark.parametrize("posture_name", ["research", "prod"])
    def test_get_gate_raises_under_strict_posture(
        self, populated_store, monkeypatch, posture_name
    ):
        monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
        with pytest.raises(ValueError, match="without tenant_id under strict"):
            populated_store.get_gate("g-a")

    def test_internal_unscoped_bypass_does_not_raise(
        self, populated_store, monkeypatch
    ):
        """``internal_unscoped=True`` is reserved for in-process callers (e.g. resolve)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        # No raise; in-process callers can read the full pool.
        rows = populated_store.list_pending(internal_unscoped=True)
        assert {r.context.gate_ref for r in rows} == {"g-a", "g-b"}
        rec = populated_store.get_gate("g-a", internal_unscoped=True)
        assert rec.context.gate_ref == "g-a"

    def test_in_memory_gate_api_strict_posture_raises(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        api = InMemoryGateAPI()
        api.create_gate(context=_ctx("m-a"), tenant_id="tenant-A")
        with pytest.raises(ValueError, match="without tenant_id under strict"):
            api.list_pending()
        with pytest.raises(ValueError, match="without tenant_id under strict"):
            api.get_gate("m-a")


class TestDevPostureDegradesGracefully:
    """Dev posture keeps legacy callers working with a WARNING log."""

    def test_dev_posture_list_pending_returns_full_pool(
        self, populated_store, monkeypatch, caplog
    ):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        with caplog.at_level("WARNING"):
            rows = populated_store.list_pending()
        assert {r.context.gate_ref for r in rows} == {"g-a", "g-b"}
        # The warning is emitted but the read proceeds.
        assert any(
            "without tenant_id" in rec.getMessage() for rec in caplog.records
        ), "expected WARNING log for unscoped read under dev posture"

    def test_dev_posture_get_gate_returns_record(
        self, populated_store, monkeypatch
    ):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        rec = populated_store.get_gate("g-b")
        assert rec.context.gate_ref == "g-b"

    def test_in_memory_gate_api_dev_posture_returns_pool(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        api = InMemoryGateAPI()
        api.create_gate(context=_ctx("m-a"), tenant_id="tenant-A")
        api.create_gate(context=_ctx("m-b"), tenant_id="tenant-B")
        rows = api.list_pending()
        assert {r.context.gate_ref for r in rows} == {"m-a", "m-b"}

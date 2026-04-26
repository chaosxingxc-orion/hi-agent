"""Integration tests: HumanGateRequest spine propagation under strict posture (Wave 10.3 W3-A)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.contracts.requests import HumanGateRequest


class TestHumanGateRequestSpineFields:
    """HumanGateRequest now carries explicit spine fields."""

    def test_default_spine_fields_are_empty_strings(self):
        req = HumanGateRequest(run_id="r1", gate_type="contract_correction", gate_ref="gr1")
        assert req.tenant_id == ""
        assert req.user_id == ""
        assert req.session_id == ""
        assert req.project_id == ""

    def test_explicit_spine_fields_set(self):
        req = HumanGateRequest(
            run_id="r1",
            gate_type="contract_correction",
            gate_ref="gr1",
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
        )
        assert req.tenant_id == "t1"
        assert req.user_id == "u1"
        assert req.session_id == "s1"
        assert req.project_id == "p1"


class TestOpenHumanGateSpinePropagation:
    """open_human_gate in kernel_facade_adapter propagates spine fields correctly."""

    def _make_adapter(self, fake_call):
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        adapter = KernelFacadeAdapter.__new__(KernelFacadeAdapter)
        adapter._call = fake_call
        adapter._current_run_id = "r1"
        # _non_empty is a @staticmethod — assign it directly
        adapter._non_empty = KernelFacadeAdapter._non_empty
        return adapter

    def test_spine_propagated_to_kernel_request_research(self, monkeypatch):
        """Under research posture, explicit spine fields reach KernelHumanGateRequest."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        captured = {}

        def fake_call(method, payload):
            captured["method"] = method
            captured["payload"] = payload

        adapter = self._make_adapter(fake_call)

        req = HumanGateRequest(
            run_id="r1",
            gate_type="contract_correction",
            gate_ref="gr-1",
            tenant_id="tenant-xyz",
            user_id="user-abc",
            session_id="sess-123",
            project_id="proj-456",
        )
        adapter.open_human_gate(req)
        payload = captured["payload"]
        assert payload.tenant_id == "tenant-xyz"
        assert payload.user_id == "user-abc"
        assert payload.session_id == "sess-123"
        assert payload.project_id == "proj-456"

    def test_empty_tenant_under_research_raises(self, monkeypatch):
        """Under research posture, open_human_gate with empty tenant_id raises ValueError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        adapter = self._make_adapter(MagicMock())

        req = HumanGateRequest(
            run_id="r1",
            gate_type="contract_correction",
            gate_ref="gr-1",
            tenant_id="",
        )
        with pytest.raises(ValueError, match="empty tenant_id"):
            adapter.open_human_gate(req)

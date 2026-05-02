"""Unit tests for hi_agent.contracts.gate_decision.GateDecisionRequest.

Layer 1 — Unit: tests for the GateDecisionRequest dataclass in isolation.
No network, no external dependencies.

# tdd-red-sha: e2c8c34a
"""
from __future__ import annotations

import os

import pytest


class TestGateDecisionRequestFields:
    """Test field validation and construction of GateDecisionRequest."""

    def test_gate_decision_request_fields(self):
        """GateDecisionRequest carries all required contract fields."""
        from hi_agent.contracts.gate_decision import GateDecisionRequest

        req = GateDecisionRequest(
            gate_id="gate-123",
            run_id="run-abc",
            tenant_id="tenant-1",
            decision="approved",
            reason="LGTM",
            decided_by="user-alice",
            decided_at="2026-05-01T12:00:00Z",
        )
        assert req.gate_id == "gate-123"
        assert req.run_id == "run-abc"
        assert req.tenant_id == "tenant-1"
        assert req.decision == "approved"
        assert req.reason == "LGTM"
        assert req.decided_by == "user-alice"
        assert req.decided_at == "2026-05-01T12:00:00Z"

    def test_gate_decision_rejected(self):
        """GateDecisionRequest accepts 'rejected' as a valid decision."""
        from hi_agent.contracts.gate_decision import GateDecisionRequest

        req = GateDecisionRequest(
            gate_id="g1",
            run_id="r1",
            tenant_id="t1",
            decision="rejected",
        )
        assert req.decision == "rejected"

    def test_gate_decision_invalid_decision_raises(self):
        """GateDecisionRequest rejects unknown decision values."""
        from hi_agent.contracts.gate_decision import GateDecisionRequest

        with pytest.raises(ValueError, match=r"approved.*rejected|rejected.*approved"):
            GateDecisionRequest(
                gate_id="g1",
                run_id="r1",
                tenant_id="t1",
                decision="maybe",
            )

    def test_gate_decision_optional_fields_default_empty(self):
        """Optional fields default to empty strings."""
        from hi_agent.contracts.gate_decision import GateDecisionRequest

        req = GateDecisionRequest(
            gate_id="g1",
            run_id="r1",
            tenant_id="t1",
            decision="approved",
        )
        assert req.reason == ""
        assert req.decided_by == ""
        assert req.decided_at == ""

    def test_gate_decision_tenant_id_is_required_field(self):
        """GateDecisionRequest has tenant_id as a named field (Rule 12)."""
        from dataclasses import fields

        from hi_agent.contracts.gate_decision import GateDecisionRequest

        field_names = {f.name for f in fields(GateDecisionRequest)}
        assert "tenant_id" in field_names, "tenant_id must be a field (Rule 12)"


class TestGateDecisionDevPosture:
    """Test posture-aware behaviour of GateDecisionRequest."""

    def test_gate_decision_dev_posture_allows_missing_tenant(self):
        """Under dev posture empty tenant_id is allowed (permissive default)."""
        original = os.environ.get("HI_AGENT_POSTURE")
        os.environ["HI_AGENT_POSTURE"] = "dev"
        try:
            from hi_agent.contracts.gate_decision import GateDecisionRequest

            # Should not raise under dev posture even with empty tenant_id.
            req = GateDecisionRequest(
                gate_id="g1",
                run_id="r1",
                tenant_id="",
                decision="approved",
            )
            assert req.tenant_id == ""
        finally:
            if original is None:
                os.environ.pop("HI_AGENT_POSTURE", None)
            else:
                os.environ["HI_AGENT_POSTURE"] = original

    def test_gate_decision_research_posture_rejects_empty_tenant(self):
        """Under research posture empty tenant_id raises ValueError (fail-closed)."""
        original = os.environ.get("HI_AGENT_POSTURE")
        os.environ["HI_AGENT_POSTURE"] = "research"
        try:
            from hi_agent.contracts.gate_decision import GateDecisionRequest

            with pytest.raises(ValueError, match="tenant_id"):
                GateDecisionRequest(
                    gate_id="g1",
                    run_id="r1",
                    tenant_id="",
                    decision="approved",
                )
        finally:
            if original is None:
                os.environ.pop("HI_AGENT_POSTURE", None)
            else:
                os.environ["HI_AGENT_POSTURE"] = original

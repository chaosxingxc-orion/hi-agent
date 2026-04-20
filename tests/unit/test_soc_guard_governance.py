"""Tests for SOC guard enforcement in GovernanceEngine.approve()."""

from __future__ import annotations

import pytest
from hi_agent.auth.soc_guard import SeparationOfConcernError
from hi_agent.harness.contracts import ActionSpec, EffectClass, SideEffectClass
from hi_agent.harness.governance import GovernanceEngine


def _approval_pending_spec(
    action_id: str = "act-1",
    submitter_id: str = "",
) -> ActionSpec:
    """Create a spec pending approval with optional submitter_id."""
    return ActionSpec(
        action_id=action_id,
        action_type="submit",
        capability_name="deploy",
        payload={"target": "prod"},
        effect_class=EffectClass.IRREVERSIBLE_WRITE,
        side_effect_class=SideEffectClass.IRREVERSIBLE_SUBMIT,
        approval_required=True,
        idempotency_key="key-1",
        submitter_id=submitter_id,
    )


class TestSocGuardGovernance:
    """Test SOC guard enforcement in GovernanceEngine.approve()."""

    def test_approve_same_submitter_and_approver_raises_error(self) -> None:
        """Test 1: approve() with same submitter and approver raises SeparationOfConcernError."""
        gov = GovernanceEngine()
        spec = _approval_pending_spec(action_id="act-1", submitter_id="alice")
        gov.request_approval(spec)

        with pytest.raises(
            SeparationOfConcernError, match="submitter and approver must be different"
        ):
            gov.approve("act-1", approver_id="alice")

        # Action should NOT be in approved set after error
        assert "act-1" not in gov._approved

    def test_approve_different_submitter_and_approver_succeeds(self) -> None:
        """Test 2: approve() with different submitter and approver succeeds."""
        gov = GovernanceEngine()
        spec = _approval_pending_spec(action_id="act-2", submitter_id="alice")
        gov.request_approval(spec)

        # Should not raise
        gov.approve("act-2", approver_id="bob")

        # Action should be in approved set
        assert "act-2" in gov._approved
        # Action should be removed from approval queue
        assert not any(s.action_id == "act-2" for s in gov._approval_queue)

    def test_approve_missing_identities_backward_compatible(self) -> None:
        """Test 3: approve() with missing identities remains backward-compatible."""
        gov = GovernanceEngine()
        spec = _approval_pending_spec(action_id="act-3", submitter_id="")
        gov.request_approval(spec)

        # Should not raise even with empty submitter_id and no approver_id
        gov.approve("act-3")

        # Action should be in approved set
        assert "act-3" in gov._approved

    def test_approve_only_approver_id_backward_compatible(self) -> None:
        """Test 4: approve() with only approver_id remains backward-compatible."""
        gov = GovernanceEngine()
        spec = _approval_pending_spec(action_id="act-4", submitter_id="")
        gov.request_approval(spec)

        # Should not raise when submitter_id is empty and approver_id is provided
        # (enabled=False because submitter_id is empty)
        gov.approve("act-4", approver_id="bob")

        # Action should be in approved set
        assert "act-4" in gov._approved

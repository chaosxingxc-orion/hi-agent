"""Integration tests for route capability availability filter (P1-2b).

MagicMock usage: legitimate use — boundary mocks on capability handler callables
registered in CapabilitySpec. The SUT (filter_proposal + real CapabilityRegistry) is
never mocked. Handler callables are external seams that represent real tool executors.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec
from hi_agent.route_engine.base import BranchProposal
from hi_agent.route_engine.capability_filter import filter_proposal


def _make_registry() -> CapabilityRegistry:
    """Return a registry pre-populated with test capabilities."""
    registry = CapabilityRegistry()

    # A known-good, always-allowed capability
    file_read_desc = CapabilityDescriptor(
        name="file_read",
        prod_enabled_default=True,
        requires_approval=False,
    )
    registry.register(
        CapabilitySpec(
            name="file_read",
            handler=MagicMock(return_value={"success": True}),
            descriptor=file_read_desc,
        )
    )

    # Disabled in prod
    shell_exec_desc = CapabilityDescriptor(
        name="shell_exec",
        prod_enabled_default=False,
        requires_approval=False,
    )
    registry.register(
        CapabilitySpec(
            name="shell_exec",
            handler=MagicMock(return_value={"success": True}),
            descriptor=shell_exec_desc,
        )
    )

    # Requires approval
    file_write_desc = CapabilityDescriptor(
        name="file_write",
        prod_enabled_default=True,
        requires_approval=True,
    )
    registry.register(
        CapabilitySpec(
            name="file_write",
            handler=MagicMock(return_value={"success": True}),
            descriptor=file_write_desc,
        )
    )

    return registry


def _proposal(action_kind: str) -> BranchProposal:
    return BranchProposal(
        branch_id="b001",
        rationale="test rationale",
        action_kind=action_kind,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unknown_capability_returns_no_action():
    """filter_proposal with an unregistered action_kind returns no_action."""
    registry = _make_registry()
    proposal = _proposal("nonexistent_tool")
    result = filter_proposal(proposal, registry, runtime_mode="dev")
    assert result.action_kind == "no_action"
    assert "unknown_capability:nonexistent_tool" in result.rationale


def test_disabled_in_prod_returns_no_action():
    """shell_exec has prod_enabled_default=False; disabled in prod-real mode."""
    registry = _make_registry()
    proposal = _proposal("shell_exec")
    result = filter_proposal(proposal, registry, runtime_mode="prod-real")
    assert result.action_kind == "no_action"
    assert "disabled_in_prod:shell_exec" in result.rationale


def test_disabled_in_prod_passes_in_dev():
    """shell_exec is allowed in non-prod runtime modes."""
    registry = _make_registry()
    proposal = _proposal("shell_exec")
    result = filter_proposal(proposal, registry, runtime_mode="dev")
    assert result.action_kind == "shell_exec"


def test_requires_approval_returns_approval_pending():
    """file_write has requires_approval=True; proposal becomes approval_pending."""
    registry = _make_registry()
    proposal = _proposal("file_write")
    result = filter_proposal(proposal, registry, runtime_mode="prod-real")
    assert result.action_kind == "approval_pending"
    assert "requires_approval:file_write" in result.rationale


def test_valid_capability_passes_through():
    """file_read is allowed in dev mode; proposal unchanged."""
    registry = _make_registry()
    proposal = _proposal("file_read")
    result = filter_proposal(proposal, registry, runtime_mode="dev")
    assert result.action_kind == "file_read"
    assert result.rationale == "test rationale"


def test_non_capability_actions_pass_through():
    """no_action and complete must pass through without any registry lookup."""
    registry = _make_registry()
    for action_kind in ("no_action", "complete", "reflect", "approval_pending", "skip"):
        proposal = _proposal(action_kind)
        result = filter_proposal(proposal, registry, runtime_mode="prod-real")
        assert result.action_kind == action_kind, (
            f"Expected {action_kind!r} to pass through unchanged"
        )


def test_branch_id_preserved_after_filter():
    """The branch_id must not be changed by the filter."""
    registry = _make_registry()
    proposal = _proposal("nonexistent_tool")
    result = filter_proposal(proposal, registry, runtime_mode="dev")
    assert result.branch_id == "b001"


def test_no_descriptor_in_prod_returns_no_action():
    """A capability registered without a CapabilityDescriptor is denied in prod-real."""
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(
            name="bare_cap",
            handler=MagicMock(return_value={"success": True}),
            descriptor=None,  # no descriptor
        )
    )
    proposal = _proposal("bare_cap")
    result = filter_proposal(proposal, registry, runtime_mode="prod-real")
    assert result.action_kind == "no_action"
    assert "no_descriptor_prod:bare_cap" in result.rationale


def test_no_descriptor_in_dev_passes_through():
    """A capability without a descriptor is allowed in dev mode."""
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(
            name="bare_cap",
            handler=MagicMock(return_value={"success": True}),
            descriptor=None,
        )
    )
    proposal = _proposal("bare_cap")
    result = filter_proposal(proposal, registry, runtime_mode="dev")
    assert result.action_kind == "bare_cap"

"""Capability availability filter for route proposals.

Validates that the proposed ``action_kind`` is registered and enabled before
the proposal reaches the invoker.  Returns a modified proposal when the
capability is unavailable or requires approval.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.capability.registry import CapabilityRegistry
    from hi_agent.route_engine.base import BranchProposal

# Actions that do not map to a registered capability.
NON_CAPABILITY_ACTIONS: frozenset[str] = frozenset(
    {"no_action", "complete", "reflect", "approval_pending", "skip"}
)


def filter_proposal(
    proposal: BranchProposal,
    registry: CapabilityRegistry,
    runtime_mode: str,
) -> BranchProposal:
    """Validate that the proposed action_kind is available and not disabled.

    Returns a modified proposal if action_kind needs to change.

    Rules:
    1. Non-capability actions (no_action, complete, reflect …) pass through.
    2. Unknown capability → replace with ``no_action``.
    3. Known capability but no descriptor → allowed in non-prod; denied in prod.
    4. ``prod_enabled_default=False`` in prod-real → replace with ``no_action``.
    5. ``requires_approval=True`` → replace with ``approval_pending``.

    Args:
        proposal: The BranchProposal emitted by the route engine.
        registry: The live CapabilityRegistry instance.
        runtime_mode: Runtime environment string, e.g. ``"prod-real"`` or ``"dev"``.

    Returns:
        The original proposal if allowed, otherwise a replacement proposal.
    """
    action_kind = proposal.action_kind

    if action_kind in NON_CAPABILITY_ACTIONS:
        return proposal

    # Check whether the capability name is registered at all.
    # CapabilityRegistry.get() raises KeyError for unknown names; use internal
    # dict lookup to avoid exception-driven control flow.
    is_registered = action_kind in registry._capabilities

    if not is_registered:
        return _replace_with_no_action(
            proposal, reason=f"unknown_capability:{action_kind}"
        )

    descriptor = registry.get_descriptor(action_kind)

    if descriptor is None:
        # Capability is registered but carries no descriptor metadata.
        if runtime_mode == "prod-real":
            return _replace_with_no_action(
                proposal, reason=f"no_descriptor_prod:{action_kind}"
            )
        return proposal

    if not descriptor.prod_enabled_default and runtime_mode == "prod-real":
        return _replace_with_no_action(
            proposal, reason=f"disabled_in_prod:{action_kind}"
        )

    if descriptor.requires_approval:
        return _replace_with_approval_pending(
            proposal, reason=f"requires_approval:{action_kind}"
        )

    return proposal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _replace_with_no_action(
    proposal: BranchProposal, reason: str
) -> BranchProposal:
    """Return a new BranchProposal with action_kind set to ``no_action``."""
    return replace(
        proposal,
        action_kind="no_action",
        rationale=f"{proposal.rationale} [capability_filter:{reason}]",
    )


def _replace_with_approval_pending(
    proposal: BranchProposal, reason: str
) -> BranchProposal:
    """Return a new BranchProposal with action_kind set to ``approval_pending``."""
    return replace(
        proposal,
        action_kind="approval_pending",
        rationale=f"{proposal.rationale} [capability_filter:{reason}]",
    )

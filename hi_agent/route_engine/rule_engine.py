"""Minimal rule-based Route Engine for spike."""

from __future__ import annotations

from typing import ClassVar

from hi_agent.contracts import deterministic_id
from hi_agent.route_engine.base import BranchProposal


class RuleRouteEngine:
    """Fixed rule route engine.

    This implementation intentionally uses one branch per stage to validate
    execution wiring before introducing probabilistic/multi-branch routing.
    """

    STAGE_ACTIONS: ClassVar[dict[str, str]] = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        """Create branch proposal for the given stage.

        Args:
          stage_id: Current stage.
          run_id: Deterministic run ID.
          seq: Monotonic action sequence.

        Returns:
          A single deterministic branch proposal.
        """
        action = self.STAGE_ACTIONS.get(stage_id, "unknown")
        branch_id = deterministic_id(run_id, stage_id, str(seq))
        return [
            BranchProposal(
                branch_id=branch_id,
                rationale=f"rule: {action}",
                action_kind=action,
            )
        ]

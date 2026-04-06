"""Hybrid route engine: rule first, then LLM fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.route_engine.base import BranchProposal
from hi_agent.route_engine.llm_engine import LLMRouteEngine
from hi_agent.route_engine.rule_engine import RuleRouteEngine


@dataclass(frozen=True)
class HybridRouteOutcome:
    """Route proposals plus provenance metadata."""

    proposals: list[BranchProposal]
    source: str
    confidence: float


class HybridRouteEngine:
    """Prefer deterministic rules and fallback to LLM for weak rule output."""

    def __init__(
        self,
        *,
        rule_engine: RuleRouteEngine | None = None,
        llm_engine: LLMRouteEngine,
        confidence_threshold: float = 0.7,
    ) -> None:
        """Initialize hybrid route policy."""
        self._rule_engine = rule_engine or RuleRouteEngine()
        self._llm_engine = llm_engine
        self._confidence_threshold = confidence_threshold

    def propose(
        self,
        stage_id: str,
        run_id: str,
        seq: int,
        *,
        context: dict[str, Any] | None = None,
    ) -> list[BranchProposal]:
        """Compatibility API used by the runner."""
        return self.propose_with_provenance(
            stage_id=stage_id,
            run_id=run_id,
            seq=seq,
            context=context,
        ).proposals

    def propose_with_provenance(
        self,
        *,
        stage_id: str,
        run_id: str,
        seq: int,
        context: dict[str, Any] | None = None,
    ) -> HybridRouteOutcome:
        """Return proposals and the source that produced them."""
        rule_proposals = self._rule_engine.propose(stage_id=stage_id, run_id=run_id, seq=seq)
        rule_confidence = self._estimate_rule_confidence(rule_proposals)
        if rule_proposals and rule_confidence >= self._confidence_threshold:
            return HybridRouteOutcome(
                proposals=rule_proposals,
                source="rule",
                confidence=rule_confidence,
            )

        llm_decision = self._llm_engine.decide(
            stage_id=stage_id,
            run_id=run_id,
            seq=seq,
            context=context,
        )
        llm_proposals = [
            BranchProposal(
                branch_id=deterministic_id(run_id, stage_id, str(seq), "llm"),
                rationale=f"llm(conf={llm_decision.confidence:.2f}): {llm_decision.rationale}",
                action_kind=llm_decision.action_kind,
            )
        ]
        return HybridRouteOutcome(
            proposals=llm_proposals,
            source="llm",
            confidence=llm_decision.confidence,
        )

    def _estimate_rule_confidence(self, proposals: list[BranchProposal]) -> float:
        if not proposals:
            return 0.0
        # In the baseline rule engine, "unknown" means no reliable deterministic route.
        if proposals[0].action_kind == "unknown":
            return 0.0
        return 1.0


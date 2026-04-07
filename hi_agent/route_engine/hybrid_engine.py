"""Hybrid route engine: rule first, then LLM fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.llm.protocol import LLMGateway
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
        llm_engine: LLMRouteEngine | None = None,
        confidence_threshold: float = 0.7,
        gateway: LLMGateway | None = None,
        skill_matcher: Any | None = None,
        task_family: str = "",
    ) -> None:
        """Initialize hybrid route policy.

        Parameters
        ----------
        rule_engine:
            Deterministic rule engine.  Defaults to :class:`RuleRouteEngine`.
            When *skill_matcher* is provided and no explicit *rule_engine* is
            given, the default rule engine is created with the matcher.
        llm_engine:
            Pre-built LLM route engine.  When *None* but *gateway* is provided,
            an :class:`LLMRouteEngine` is created automatically using the gateway.
        confidence_threshold:
            Rule confidence must meet this threshold to skip LLM.
        gateway:
            Optional :class:`LLMGateway`.  Passed through to the LLM engine
            when *llm_engine* is not explicitly provided.
        skill_matcher:
            Optional :class:`~hi_agent.skill.matcher.SkillMatcher`.  Passed
            through to the rule engine for skill-aware proposals.
        task_family:
            Task family string for skill applicability matching.
        """
        if rule_engine is not None:
            self._rule_engine = rule_engine
        else:
            self._rule_engine = RuleRouteEngine(
                skill_matcher=skill_matcher,
                task_family=task_family,
            )
        self._skill_matcher = skill_matcher
        self._task_family = task_family
        if llm_engine is not None:
            self._llm_engine = llm_engine
        else:
            self._llm_engine = LLMRouteEngine(gateway=gateway)
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

        # Annotate LLM proposals with matching skill_ids when available.
        skill_annotation = ""
        if self._skill_matcher is not None:
            matched = self._skill_matcher.match(
                task_family=self._task_family,
                stage_id=stage_id,
                context=context,
            )
            if matched:
                skill_ids = [s.skill_id for s in matched]
                skill_annotation = f" skills={skill_ids}"

        llm_proposals = [
            BranchProposal(
                branch_id=deterministic_id(run_id, stage_id, str(seq), "llm"),
                rationale=f"llm(conf={llm_decision.confidence:.2f}): {llm_decision.rationale}{skill_annotation}",
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


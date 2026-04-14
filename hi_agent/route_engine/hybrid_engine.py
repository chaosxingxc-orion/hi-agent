"""Hybrid route engine: rule first, then LLM fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.llm.protocol import LLMGateway
from hi_agent.route_engine.base import BranchProposal
from hi_agent.route_engine.decision_audit import persist_route_decision_audit
from hi_agent.route_engine.llm_engine import LLMRouteEngine
from hi_agent.route_engine.rule_engine import RuleRouteEngine

_logger = logging.getLogger(__name__)


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
        audit_store: Any | None = None,
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
        # In-memory list used as append-only audit log; callers may inject
        # a persistent store by passing audit_store with an .append() method.
        self._audit_store: Any = audit_store if audit_store is not None else []

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
        rule_proposals = self._rule_engine.propose(
            stage_id=stage_id,
            run_id=run_id,
            seq=seq,
        )
        rule_confidence = self._estimate_rule_confidence(rule_proposals)
        if rule_proposals and rule_confidence >= self._confidence_threshold:
            outcome = HybridRouteOutcome(
                proposals=rule_proposals,
                source="rule",
                confidence=rule_confidence,
            )
            self._persist_audit(run_id, stage_id, outcome, seq)
            return outcome

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
                rationale=(
                    f"llm(conf={llm_decision.confidence:.2f}): "
                    f"{llm_decision.rationale}{skill_annotation}"
                ),
                action_kind=llm_decision.action_kind,
            )
        ]
        outcome = HybridRouteOutcome(
            proposals=llm_proposals,
            source="llm",
            confidence=llm_decision.confidence,
        )
        self._persist_audit(run_id, stage_id, outcome, seq)
        return outcome

    def _persist_audit(
        self,
        run_id: str,
        stage_id: str,
        outcome: HybridRouteOutcome,
        seq: int,
    ) -> None:
        """Persist route decision audit record (best-effort)."""
        try:
            selected = outcome.proposals[0].branch_id if outcome.proposals else ""
            candidates = [
                {"branch_id": p.branch_id, "rationale": p.rationale}
                for p in outcome.proposals
            ]
            persist_route_decision_audit(
                self._audit_store,
                run_id=run_id,
                stage_id=stage_id,
                engine=outcome.source,
                provenance=outcome.source,
                selected_branch=selected,
                candidates=candidates,
                confidence=outcome.confidence,
            )
        except Exception as _exc:
            _logger.debug(
                "HybridRouteEngine: audit persist failed (run_id=%s stage_id=%s): %s",
                run_id, stage_id, _exc,
            )

    def apply_evolve_changes(self, changes: list) -> None:
        """Apply EvolveResult changes to tune routing thresholds.

        Parameters
        ----------
        changes:
            List of :class:`~hi_agent.evolve.types.EvolveChange` (or any
            object with ``change_type``, ``confidence``, and ``target_id``
            attributes) produced by :class:`~hi_agent.evolve.engine.EvolveEngine`.
        """
        for change in changes:
            change_type = getattr(change, "change_type", None)
            confidence = getattr(change, "confidence", 0.0)
            target_id = getattr(change, "target_id", "")
            if change_type == "routing_heuristic" and confidence >= 0.7:
                # Exploration failure detected — lower threshold so LLM fallback
                # is triggered more readily.
                old = self._confidence_threshold
                self._confidence_threshold = max(0.3, self._confidence_threshold - 0.05)
                _logger.info(
                    "route_engine.apply_evolve_changes type=%s target=%s "
                    "confidence=%.2f threshold %.2f -> %.2f",
                    change_type, target_id, confidence, old, self._confidence_threshold,
                )
            elif change_type == "efficiency_heuristic" and confidence >= 0.7:
                # Efficiency signal — raise threshold to prefer deterministic rules.
                old = self._confidence_threshold
                self._confidence_threshold = min(0.9, self._confidence_threshold + 0.05)
                _logger.info(
                    "route_engine.apply_evolve_changes type=%s target=%s "
                    "confidence=%.2f threshold %.2f -> %.2f",
                    change_type, target_id, confidence, old, self._confidence_threshold,
                )
            elif change_type == "route_config_updated" and confidence >= 0.6:
                # Structured config update: target_id encodes "key:value"
                # e.g. "confidence_threshold:0.75" or "prefer_llm_for:analysis"
                self._apply_route_config_update(target_id, confidence)
            else:
                _logger.info(
                    "route_engine.apply_evolve_changes skipped type=%s target=%s "
                    "confidence=%.2f (below threshold or unrecognised type)",
                    change_type, target_id, confidence,
                )

    def _apply_route_config_update(self, target_id: str, confidence: float) -> None:
        """Parse and apply a structured route_config_updated change.

        Format: ``"key:value"`` e.g. ``"confidence_threshold:0.75"``.
        """
        if ":" not in target_id:
            _logger.debug(
                "route_engine.route_config_update invalid target_id=%s", target_id
            )
            return
        key, _, raw_value = target_id.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if key == "confidence_threshold":
            try:
                new_val = float(raw_value)
                new_val = max(0.1, min(0.99, new_val))
                old = self._confidence_threshold
                self._confidence_threshold = new_val
                _logger.info(
                    "route_engine.route_config_updated key=%s confidence=%.2f "
                    "threshold %.2f -> %.2f",
                    key, confidence, old, new_val,
                )
            except ValueError:
                _logger.debug(
                    "route_engine.route_config_update bad value key=%s value=%s",
                    key, raw_value,
                )
        else:
            _logger.debug(
                "route_engine.route_config_update unknown key=%s", key
            )

    def _estimate_rule_confidence(self, proposals: list[BranchProposal]) -> float:
        """Run _estimate_rule_confidence."""
        if not proposals:
            return 0.0
        # In the baseline rule engine, "unknown" means no reliable deterministic route.
        if proposals[0].action_kind == "unknown":
            return 0.0
        return 1.0


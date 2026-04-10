"""Minimal rule-based Route Engine for spike."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, ClassVar

from hi_agent.contracts import deterministic_id
from hi_agent.route_engine.base import BranchProposal

_logger = logging.getLogger(__name__)

# Clamp bounds for confidence delta accumulation.
_CONFIDENCE_MIN = 0.05
_CONFIDENCE_MAX = 1.0

# Default base confidence for a stage (used when no override is set).
_DEFAULT_STAGE_CONFIDENCE = 0.5

# Weight applied to rule proposals; higher weight = placed earlier.
_DEFAULT_ACTION_WEIGHT = 1.0


class RuleRouteEngine:
    """Fixed rule route engine.

    This implementation intentionally uses one branch per stage to validate
    execution wiring before introducing probabilistic/multi-branch routing.

    When a :class:`SkillMatcher` is provided, the engine also queries for
    certified skills applicable to the current stage and task family.  Matched
    skills are emitted as additional branch proposals with higher priority
    (placed before the generic rule proposal).

    Evolve integration
    ------------------
    ``apply_evolve_changes()`` consumes :class:`~hi_agent.evolve.contracts.EvolveChange`
    objects and updates two internal tables:

    * ``_stage_confidence`` – per-stage confidence overrides driven by
      ``routing_heuristic`` changes.  Stages with higher confidence keep their
      generic rule proposal at the front of the list; stages below 0.5 have it
      moved behind skill proposals.
    * ``_action_weights`` – per-stage action weight overrides driven by
      ``skill_update`` changes.  When multiple rule proposals would be produced
      for the same stage (future extension), they are sorted by descending weight.

    Both tables are persisted to ``_evolve_state_path`` (JSON) so that
    improvements survive process restarts.
    """

    STAGE_ACTIONS: ClassVar[dict[str, str]] = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    # Priority constants - lower numeric value = higher priority.
    _SKILL_BASE_PRIORITY: ClassVar[int] = 10
    _SKILL_PRECONDITION_BOOST: ClassVar[int] = 5
    _RULE_PRIORITY: ClassVar[int] = 50

    def __init__(
        self,
        *,
        skill_matcher: Any | None = None,
        task_family: str = "",
        context: dict[str, Any] | None = None,
        evolve_state_path: str | None = None,
    ) -> None:
        """Initialise the rule engine with optional skill matching.

        Parameters
        ----------
        skill_matcher:
            A :class:`~hi_agent.skill.matcher.SkillMatcher` instance.  When
            provided, ``propose()`` will also return skill-based proposals.
        task_family:
            Task family string used for skill applicability matching.
        context:
            Optional context dict passed to the skill matcher for
            precondition / forbidden-condition evaluation.
        evolve_state_path:
            Optional file path for persisting evolve state (confidence and
            action-weight tables) across process restarts.  When *None*, state
            is kept in-memory only.
        """
        self._skill_matcher = skill_matcher
        self._task_family = task_family
        self._context: dict[str, Any] = context or {}

        # --- Evolve dynamic state -------------------------------------------
        # stage_id → confidence override in [_CONFIDENCE_MIN, _CONFIDENCE_MAX]
        self._stage_confidence: dict[str, float] = {}
        # stage_id → action → weight (higher = preferred)
        self._action_weights: dict[str, dict[str, float]] = {}

        self._evolve_state_path: str | None = evolve_state_path
        self._load_evolve_state()

    # ------------------------------------------------------------------
    # Core routing
    # ------------------------------------------------------------------

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        """Create branch proposals for the given stage.

        When a skill matcher is configured, certified skills that match the
        current task family and stage are returned as additional proposals.

        Proposal ordering is influenced by evolve state:
        - If the stage confidence override is >= 0.5 (or unset), the generic
          rule proposal is placed *before* skill proposals (rule-first).
        - If the stage confidence override is < 0.5, skill proposals lead and
          the rule proposal is appended at the end.

        Args:
          stage_id: Current stage.
          run_id: Deterministic run ID.
          seq: Monotonic action sequence.

        Returns:
          A list of branch proposals ordered by current evolve weights.
        """
        # --- Generic rule proposal ------------------------------------------
        action = self._best_action(stage_id)
        branch_id = deterministic_id(run_id, stage_id, str(seq))
        stage_conf = self._stage_confidence.get(stage_id, _DEFAULT_STAGE_CONFIDENCE)
        rule_proposal = BranchProposal(
            branch_id=branch_id,
            rationale=f"rule: {action} (conf={stage_conf:.2f})",
            action_kind=action,
        )

        # --- Skill-based proposals ------------------------------------------
        skill_proposals: list[BranchProposal] = []
        if self._skill_matcher is not None:
            matched = self._skill_matcher.match(
                task_family=self._task_family,
                stage_id=stage_id,
                context=self._context,
            )
            for _idx, skill in enumerate(matched):
                skill_branch_id = deterministic_id(
                    run_id, stage_id, str(seq), "skill", skill.skill_id,
                )
                skill_proposals.append(
                    BranchProposal(
                        branch_id=skill_branch_id,
                        rationale=f"skill:{skill.skill_id}(evidence={skill.evidence_count})",
                        action_kind=skill.name,
                    )
                )

        # --- Ordering driven by stage confidence ----------------------------
        # Original default: skill proposals lead, rule proposal is the fallback.
        # When evolve has explicitly raised stage confidence above the default
        # threshold (> 0.5), the rule proposal is promoted to the front.
        if stage_id in self._stage_confidence and stage_conf > _DEFAULT_STAGE_CONFIDENCE:
            # Evolve has increased confidence in the rule: rule first, then skills.
            return [rule_proposal] + skill_proposals
        else:
            # Default or low confidence: prefer skills, fallback to rule.
            return skill_proposals + [rule_proposal]

    # ------------------------------------------------------------------
    # Evolve integration
    # ------------------------------------------------------------------

    def apply_evolve_changes(self, changes: list) -> None:
        """Apply evolve improvement signals to update routing state.

        Processes two change types:

        ``routing_heuristic``
            Adjusts the confidence override for the targeted stage.  The
            ``confidence`` field of the change is used as an absolute new
            value when it is meaningful (> 0), otherwise a small delta is
            applied.  Multiple changes for the same stage are accumulated and
            clamped to ``[_CONFIDENCE_MIN, _CONFIDENCE_MAX]``.

        ``skill_update``
            Updates the action weight table for the targeted stage so that the
            action named in the change description is preferred during routing.
            The weight is set to the change's ``confidence`` value.

        After processing all changes the updated tables are persisted to
        ``_evolve_state_path`` when that attribute is set.

        Args:
            changes: List of :class:`~hi_agent.evolve.contracts.EvolveChange`
                objects (or duck-typed equivalents with the same attributes).
        """
        applied = 0
        for change in changes:
            change_type = getattr(change, "change_type", None)
            target_id = getattr(change, "target_id", "")
            confidence = getattr(change, "confidence", 0.0)
            description = getattr(change, "description", "")

            if change_type == "routing_heuristic":
                # target_id may be a qualified key like "task_family:foo" or
                # "branch_efficiency:foo" — extract the stage portion when the
                # target directly names a known stage; otherwise store as-is
                # so that broad heuristics are still recorded.
                stage_key = _extract_stage_key(target_id, self.STAGE_ACTIONS)
                current = self._stage_confidence.get(stage_key, _DEFAULT_STAGE_CONFIDENCE)
                # Use the confidence value as a positive signal: shift current
                # confidence toward the change's confidence value by a weighted
                # step so that repeated high-confidence signals accumulate.
                delta = (confidence - current) * 0.25
                updated = max(_CONFIDENCE_MIN, min(_CONFIDENCE_MAX, current + delta))
                self._stage_confidence[stage_key] = updated
                _logger.info(
                    "rule_engine.evolve routing_heuristic target=%s "
                    "confidence %.2f→%.2f",
                    stage_key, current, updated,
                )
                applied += 1

            elif change_type == "skill_update":
                # target_id should be a stage_id; description may name action.
                stage_key = _extract_stage_key(target_id, self.STAGE_ACTIONS)
                weights = self._action_weights.setdefault(stage_key, {})
                # Attempt to infer an action name from the description, falling
                # back to the stage's default action.
                action = _infer_action_from_description(
                    description, self.STAGE_ACTIONS, stage_key
                )
                old_weight = weights.get(action, _DEFAULT_ACTION_WEIGHT)
                # Weight grows with repeated positive signals.
                weights[action] = max(0.01, confidence)
                _logger.info(
                    "rule_engine.evolve skill_update stage=%s action=%s "
                    "weight %.2f→%.2f",
                    stage_key, action, old_weight, weights[action],
                )
                applied += 1

            else:
                _logger.debug(
                    "rule_engine.apply_evolve_changes ignored type=%s target=%s "
                    "confidence=%.2f",
                    change_type, target_id, confidence,
                )

        if applied:
            self._persist_evolve_state()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _best_action(self, stage_id: str) -> str:
        """Return the best action for *stage_id* considering evolve weights."""
        default_action = self.STAGE_ACTIONS.get(stage_id, "unknown")
        weights = self._action_weights.get(stage_id)
        if not weights:
            return default_action
        # Pick the action with the highest weight; default_action is the
        # baseline candidate at weight 1.0.
        candidates = {default_action: _DEFAULT_ACTION_WEIGHT, **weights}
        return max(candidates, key=lambda a: candidates[a])

    def _load_evolve_state(self) -> None:
        """Load persisted evolve state from ``_evolve_state_path`` if it exists."""
        if not self._evolve_state_path:
            return
        try:
            if os.path.exists(self._evolve_state_path):
                with open(self._evolve_state_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._stage_confidence = {
                    k: float(v)
                    for k, v in data.get("stage_confidence", {}).items()
                }
                self._action_weights = {
                    k: {ak: float(av) for ak, av in v.items()}
                    for k, v in data.get("action_weights", {}).items()
                }
                _logger.debug(
                    "rule_engine: loaded evolve state from %s",
                    self._evolve_state_path,
                )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "rule_engine: failed to load evolve state from %s: %s",
                self._evolve_state_path, exc,
            )

    def _persist_evolve_state(self) -> None:
        """Persist current evolve state to ``_evolve_state_path``."""
        if not self._evolve_state_path:
            return
        try:
            data = {
                "stage_confidence": self._stage_confidence,
                "action_weights": self._action_weights,
            }
            with open(self._evolve_state_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            _logger.debug(
                "rule_engine: persisted evolve state to %s",
                self._evolve_state_path,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "rule_engine: failed to persist evolve state to %s: %s",
                self._evolve_state_path, exc,
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _extract_stage_key(target_id: str, stage_actions: dict[str, str]) -> str:
    """Extract a usable lookup key from a change target_id.

    If *target_id* exactly matches a known stage ID, it is returned as-is.
    Otherwise the raw *target_id* is kept so that broad heuristics (e.g.
    ``"task_family:analysis"``) are still stored and can influence future
    lookups.

    Args:
        target_id: The ``target_id`` from an :class:`EvolveChange`.
        stage_actions: The engine's ``STAGE_ACTIONS`` mapping.

    Returns:
        A string key suitable for use in ``_stage_confidence`` or
        ``_action_weights``.
    """
    if target_id in stage_actions:
        return target_id
    return target_id


def _infer_action_from_description(
    description: str,
    stage_actions: dict[str, str],
    stage_key: str,
) -> str:
    """Try to infer an action name from a change description.

    Looks for any known action string as a substring of *description*.
    Falls back to the stage's default action from *stage_actions*, or
    ``"unknown"`` if the stage is not recognised.

    Args:
        description: The change description text.
        stage_actions: The engine's ``STAGE_ACTIONS`` mapping.
        stage_key: The stage identifier to fall back to.

    Returns:
        An action string.
    """
    known_actions = set(stage_actions.values())
    for action in known_actions:
        if action in description:
            return action
    return stage_actions.get(stage_key, "unknown")

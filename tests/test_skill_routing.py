"""Tests for skill-aware routing integration."""

from __future__ import annotations

from hi_agent.route_engine.base import BranchProposal
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.route_engine.skill_aware_engine import SkillAwareRouteEngine
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.registry import ManagedSkill, SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_certified_skill(
    skill_id: str,
    name: str = "do_something",
    scope: str = "*",
    evidence: int = 10,
    preconditions: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> ManagedSkill:
    return ManagedSkill(
        skill_id=skill_id,
        name=name,
        description=f"Skill {skill_id}",
        lifecycle_stage="certified",
        applicability_scope=scope,
        preconditions=preconditions or [],
        forbidden_conditions=forbidden or [],
        evidence_count=evidence,
    )


def _registry_with_skills(*skills: ManagedSkill) -> SkillRegistry:
    reg = SkillRegistry()
    for s in skills:
        reg._skills[s.skill_id] = s
    return reg


class _StubInnerEngine:
    """Minimal inner engine for testing SkillAwareRouteEngine."""

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        return [
            BranchProposal(
                branch_id=f"inner-{stage_id}-{seq}",
                rationale="inner fallback",
                action_kind="generic_action",
            )
        ]


# ---------------------------------------------------------------------------
# RuleRouteEngine + SkillMatcher
# ---------------------------------------------------------------------------

class TestRuleRouteEngineWithSkills:
    """RuleRouteEngine finds applicable skills when skill_matcher is set."""

    def test_skill_proposals_appear_before_rule(self) -> None:
        skill = _make_certified_skill("sk1", name="fast_analyze", scope="*")
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(skill_matcher=matcher, task_family="qa")
        proposals = engine.propose("S1_understand", "run-1", 0)

        # First proposal should be skill-based, last should be rule-based.
        assert len(proposals) >= 2
        assert "skill:sk1" in proposals[0].rationale
        assert proposals[-1].rationale.startswith("rule:")

    def test_no_matcher_returns_single_rule_proposal(self) -> None:
        engine = RuleRouteEngine()
        proposals = engine.propose("S1_understand", "run-1", 0)
        assert len(proposals) == 1
        assert proposals[0].rationale.startswith("rule:")

    def test_no_certified_skills_returns_rule_only(self) -> None:
        # Registry with a candidate (not certified) skill.
        skill = _make_certified_skill("sk_cand", scope="*")
        skill.lifecycle_stage = "candidate"
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(skill_matcher=matcher, task_family="qa")
        proposals = engine.propose("S2_gather", "run-2", 1)
        assert len(proposals) == 1
        assert proposals[0].rationale.startswith("rule:")


# ---------------------------------------------------------------------------
# Skill proposals have higher priority than generic proposals
# ---------------------------------------------------------------------------

class TestSkillPriority:
    """Skill-based proposals have higher priority (appear first)."""

    def test_skill_before_generic(self) -> None:
        s1 = _make_certified_skill("sk_hi", name="hi_action", evidence=20)
        s2 = _make_certified_skill("sk_lo", name="lo_action", evidence=5)
        reg = _registry_with_skills(s1, s2)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(skill_matcher=matcher, task_family="qa")
        proposals = engine.propose("S3_build", "run-3", 2)

        # Skills appear first (ordered by evidence desc), then generic rule.
        assert len(proposals) == 3
        assert "sk_hi" in proposals[0].rationale
        assert "sk_lo" in proposals[1].rationale
        assert proposals[2].rationale.startswith("rule:")

    def test_higher_evidence_skill_first(self) -> None:
        s_low = _make_certified_skill("sk_low", evidence=2)
        s_high = _make_certified_skill("sk_high", evidence=50)
        reg = _registry_with_skills(s_low, s_high)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(skill_matcher=matcher, task_family="*")
        # Both have scope="*", so both match task_family="*".
        proposals = engine.propose("S1_understand", "run-4", 0)

        skill_proposals = [p for p in proposals if "skill:" in p.rationale]
        assert len(skill_proposals) == 2
        # Higher evidence first (matcher sorts descending).
        assert "sk_high" in skill_proposals[0].rationale
        assert "sk_low" in skill_proposals[1].rationale


# ---------------------------------------------------------------------------
# SkillAwareRouteEngine
# ---------------------------------------------------------------------------

class TestSkillAwareRouteEngine:
    """SkillAwareRouteEngine merges skill and inner proposals."""

    def test_merge_skill_and_inner(self) -> None:
        skill = _make_certified_skill("sk_a", name="analyze_deep", evidence=15)
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        inner = _StubInnerEngine()
        engine = SkillAwareRouteEngine(
            inner=inner, skill_matcher=matcher, task_family="research",
        )
        proposals = engine.propose("S2_gather", "run-5", 0)

        # Should have skill proposal + inner proposal.
        assert len(proposals) == 2
        assert "skill:sk_a" in proposals[0].rationale
        assert proposals[1].rationale == "inner fallback"

    def test_no_skills_falls_back_to_inner_only(self) -> None:
        reg = SkillRegistry()  # empty
        matcher = SkillMatcher(reg)
        inner = _StubInnerEngine()

        engine = SkillAwareRouteEngine(
            inner=inner, skill_matcher=matcher, task_family="anything",
        )
        proposals = engine.propose("S1_understand", "run-6", 0)

        assert len(proposals) == 1
        assert proposals[0].rationale == "inner fallback"

    def test_deduplication_by_branch_id(self) -> None:
        """If inner and skill produce the same branch_id, keep only the first."""
        skill = _make_certified_skill("sk_dup", name="dup_action", evidence=5)
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        class _DupInner:
            def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
                # Return a branch that will NOT collide (different branch_id).
                return [
                    BranchProposal(
                        branch_id="unique-inner",
                        rationale="inner unique",
                        action_kind="inner_action",
                    ),
                ]

        engine = SkillAwareRouteEngine(
            inner=_DupInner(), skill_matcher=matcher, task_family="test",
        )
        proposals = engine.propose("S3_build", "run-7", 0)
        ids = [p.branch_id for p in proposals]
        assert len(ids) == len(set(ids)), "No duplicate branch_ids"


# ---------------------------------------------------------------------------
# Precondition filtering
# ---------------------------------------------------------------------------

class TestPreconditionFiltering:
    """Skills with unmet preconditions are excluded."""

    def test_precondition_met(self) -> None:
        skill = _make_certified_skill(
            "sk_pre", name="guarded_action",
            preconditions=["has_data"],
        )
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(
            skill_matcher=matcher,
            task_family="qa",
            context={"has_data": True},
        )
        proposals = engine.propose("S2_gather", "run-8", 0)
        skill_proposals = [p for p in proposals if "skill:" in p.rationale]
        assert len(skill_proposals) == 1

    def test_precondition_not_met(self) -> None:
        skill = _make_certified_skill(
            "sk_pre2", name="guarded_action",
            preconditions=["has_data"],
        )
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(
            skill_matcher=matcher,
            task_family="qa",
            context={"has_data": False},
        )
        proposals = engine.propose("S2_gather", "run-9", 0)
        skill_proposals = [p for p in proposals if "skill:" in p.rationale]
        assert len(skill_proposals) == 0

    def test_forbidden_condition_blocks_skill(self) -> None:
        skill = _make_certified_skill(
            "sk_forbid", name="risky_action",
            forbidden=["is_production"],
        )
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(
            skill_matcher=matcher,
            task_family="qa",
            context={"is_production": True},
        )
        proposals = engine.propose("S3_build", "run-10", 0)
        skill_proposals = [p for p in proposals if "skill:" in p.rationale]
        assert len(skill_proposals) == 0

    def test_no_context_assumes_preconditions_met(self) -> None:
        skill = _make_certified_skill(
            "sk_nocheck", name="easy_action",
            preconditions=["something"],
        )
        reg = _registry_with_skills(skill)
        matcher = SkillMatcher(reg)

        engine = RuleRouteEngine(
            skill_matcher=matcher,
            task_family="qa",
        )
        proposals = engine.propose("S1_understand", "run-11", 0)
        skill_proposals = [p for p in proposals if "skill:" in p.rationale]
        # With no context, preconditions assumed met.
        assert len(skill_proposals) == 1

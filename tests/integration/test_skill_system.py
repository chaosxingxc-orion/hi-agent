"""Tests for the full Skill lifecycle management system."""

from __future__ import annotations

import os
import tempfile

import pytest
from hi_agent.evolve.skill_extractor import SkillCandidate
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import ManagedSkill, SkillRegistry
from hi_agent.skill.validator import SkillValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    skill_id: str = "skill_abc",
    name: str = "TestSkill",
    description: str = "A test skill",
    scope: str = "python_backend",
    evidence: int = 1,
    run_ids: list[str] | None = None,
) -> SkillCandidate:
    return SkillCandidate(
        skill_id=skill_id,
        name=name,
        description=description,
        applicability_scope=scope,
        preconditions=["task_family == 'python_backend'"],
        evidence_count=evidence,
        source_run_ids=run_ids or ["run_001"],
    )


def _promote_to_certified(registry: SkillRegistry, skill_id: str) -> ManagedSkill:
    """Helper: fast-track a skill to certified by setting counts directly."""
    skill = registry.get(skill_id)
    assert skill is not None, f"Expected non-None result for skill"
    # Meet provisional criteria
    skill.evidence_count = 2
    registry.promote(skill_id, "provisional", evidence=["e1", "e2"])
    # Meet certified criteria
    skill.evidence_count = 5
    skill.success_count = 5
    skill.failure_count = 0
    registry.promote(skill_id, "certified", evidence=["e3", "e4", "e5"])
    return skill


# ---------------------------------------------------------------------------
# SkillRegistry tests
# ---------------------------------------------------------------------------


class TestSkillRegistry:
    def test_register_candidate(self) -> None:
        reg = SkillRegistry()
        candidate = _make_candidate()
        skill = reg.register_candidate(candidate)

        assert skill.skill_id == "skill_abc"
        assert skill.lifecycle_stage == "candidate"
        assert skill.name == "TestSkill"
        assert skill.evidence_count == 1
        assert skill.created_at != ""

    def test_register_duplicate_merges(self) -> None:
        reg = SkillRegistry()
        c1 = _make_candidate(run_ids=["run_001"])
        c2 = _make_candidate(evidence=2, run_ids=["run_002"])

        reg.register_candidate(c1)
        skill = reg.register_candidate(c2)

        assert skill.evidence_count == 3  # 1 + 2
        assert "run_001" in skill.source_run_ids
        assert "run_002" in skill.source_run_ids

    def test_get_returns_none_for_missing(self) -> None:
        reg = SkillRegistry()
        assert reg.get("nonexistent") is None

    def test_promote_candidate_to_provisional(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate(evidence=3))
        skill = reg.promote("skill_abc", "provisional", evidence=["ev1"])

        assert skill.lifecycle_stage == "provisional"
        assert len(skill.promotion_history) == 1
        assert skill.promotion_history[0].from_stage == "candidate"
        assert skill.promotion_history[0].to_stage == "provisional"

    def test_promote_full_lifecycle(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate(evidence=2))

        reg.promote("skill_abc", "provisional")
        skill = reg.get("skill_abc")
        assert skill is not None, f"Expected non-None result for skill"
        skill.evidence_count = 6
        skill.success_count = 5
        skill.failure_count = 1

        reg.promote("skill_abc", "certified")
        assert skill.lifecycle_stage == "certified"

        reg.deprecate("skill_abc", reason="Replaced by v2")
        assert skill.lifecycle_stage == "deprecated"

        reg.retire("skill_abc")
        assert skill.lifecycle_stage == "retired"
        assert len(skill.promotion_history) == 4

    def test_illegal_transition_rejected(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate())

        with pytest.raises(ValueError, match="not a legal lifecycle transition"):
            reg.promote("skill_abc", "certified")

    def test_promote_missing_skill_raises(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(KeyError):
            reg.promote("no_such_skill", "provisional")

    def test_deprecate_non_certified_raises(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate(evidence=3))
        reg.promote("skill_abc", "provisional")

        with pytest.raises(ValueError, match="Can only deprecate certified"):
            reg.deprecate("skill_abc", reason="test")

    def test_retire_non_deprecated_raises(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate(evidence=3))

        with pytest.raises(ValueError, match="Can only retire deprecated"):
            reg.retire("skill_abc")

    def test_list_by_stage(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate("s1", evidence=3))
        reg.register_candidate(_make_candidate("s2", evidence=3))
        reg.promote("s1", "provisional")

        assert len(reg.list_by_stage("candidate")) == 1
        assert len(reg.list_by_stage("provisional")) == 1

    def test_list_certified(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate("s1", evidence=2))
        _promote_to_certified(reg, "s1")

        certified = reg.list_certified()
        assert len(certified) == 1
        assert certified[0].skill_id == "s1"

    def test_list_applicable(self) -> None:
        reg = SkillRegistry()
        # Skill matching python_backend
        reg.register_candidate(_make_candidate("s1", scope="python_backend", evidence=2))
        _promote_to_certified(reg, "s1")

        # Skill matching wildcard
        reg.register_candidate(_make_candidate("s2", scope="*", evidence=2))
        _promote_to_certified(reg, "s2")

        # Skill matching different scope
        reg.register_candidate(_make_candidate("s3", scope="java_backend", evidence=2))
        _promote_to_certified(reg, "s3")

        applicable = reg.list_applicable("python_backend", "S1")
        ids = [s.skill_id for s in applicable]
        assert "s1" in ids
        assert "s2" in ids
        assert "s3" not in ids

    def test_persistence_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = SkillRegistry(storage_dir=tmpdir)
            reg.register_candidate(_make_candidate(evidence=3))
            reg.promote("skill_abc", "provisional", evidence=["e1"])
            reg.save()

            # Verify file exists
            path = os.path.join(tmpdir, "registry.json")
            assert os.path.exists(path)

            # Load into fresh registry
            reg2 = SkillRegistry(storage_dir=tmpdir)
            reg2.load()

            skill = reg2.get("skill_abc")
            assert skill is not None, f"Expected non-None result for skill"
            assert skill.lifecycle_stage == "provisional"
            assert len(skill.promotion_history) == 1
            assert skill.promotion_history[0].from_stage == "candidate"

    def test_load_nonexistent_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = SkillRegistry(storage_dir=os.path.join(tmpdir, "nope"))
            reg.load()  # Should not raise
            assert reg.get("anything") is None


# ---------------------------------------------------------------------------
# SkillValidator tests
# ---------------------------------------------------------------------------


class TestSkillValidator:
    def test_valid_candidate_to_provisional(self) -> None:
        v = SkillValidator()
        skill = ManagedSkill(
            skill_id="s1",
            name="S",
            description="D",
            lifecycle_stage="candidate",
            evidence_count=3,
        )
        ok, _ = v.can_promote(skill, "provisional")
        assert ok is True

    def test_insufficient_evidence_for_provisional(self) -> None:
        v = SkillValidator()
        skill = ManagedSkill(
            skill_id="s1",
            name="S",
            description="D",
            lifecycle_stage="candidate",
            evidence_count=1,
        )
        ok, reason = v.can_promote(skill, "provisional")
        assert ok is False
        assert "evidence" in reason.lower()

    def test_valid_provisional_to_certified(self) -> None:
        v = SkillValidator()
        skill = ManagedSkill(
            skill_id="s1",
            name="S",
            description="D",
            lifecycle_stage="provisional",
            evidence_count=5,
            success_count=4,
            failure_count=1,
        )
        ok, _ = v.can_promote(skill, "certified")
        assert ok is True

    def test_low_success_rate_blocks_certified(self) -> None:
        v = SkillValidator()
        skill = ManagedSkill(
            skill_id="s1",
            name="S",
            description="D",
            lifecycle_stage="provisional",
            evidence_count=5,
            success_count=3,
            failure_count=2,
        )
        ok, reason = v.can_promote(skill, "certified")
        assert ok is False
        assert "success rate" in reason.lower()

    def test_no_usage_data_blocks_certified(self) -> None:
        v = SkillValidator()
        skill = ManagedSkill(
            skill_id="s1",
            name="S",
            description="D",
            lifecycle_stage="provisional",
            evidence_count=5,
        )
        ok, reason = v.can_promote(skill, "certified")
        assert ok is False
        assert "usage data" in reason.lower()

    def test_illegal_transition(self) -> None:
        v = SkillValidator()
        assert v.validate_transition("candidate", "certified") is False
        assert v.validate_transition("retired", "candidate") is False

    def test_legal_transitions(self) -> None:
        v = SkillValidator()
        assert v.validate_transition("candidate", "provisional") is True
        assert v.validate_transition("provisional", "certified") is True
        assert v.validate_transition("certified", "deprecated") is True
        assert v.validate_transition("deprecated", "retired") is True

    def test_custom_thresholds(self) -> None:
        v = SkillValidator(
            min_provisional_evidence=1,
            min_certified_evidence=3,
            min_certified_success_rate=0.5,
        )
        skill = ManagedSkill(
            skill_id="s1",
            name="S",
            description="D",
            lifecycle_stage="candidate",
            evidence_count=1,
        )
        ok, _ = v.can_promote(skill, "provisional")
        assert ok is True


# ---------------------------------------------------------------------------
# SkillMatcher tests
# ---------------------------------------------------------------------------


class TestSkillMatcher:
    def _setup_certified_skill(
        self,
        reg: SkillRegistry,
        skill_id: str = "s1",
        scope: str = "python_backend",
        preconditions: list[str] | None = None,
        forbidden: list[str] | None = None,
    ) -> ManagedSkill:
        c = SkillCandidate(
            skill_id=skill_id,
            name="Sk",
            description="D",
            applicability_scope=scope,
            preconditions=preconditions or [],
            evidence_count=2,
            source_run_ids=["r1"],
        )
        reg.register_candidate(c)
        skill = reg.get(skill_id)
        assert skill is not None, f"Expected non-None result for skill"
        if forbidden:
            skill.forbidden_conditions = forbidden
        _promote_to_certified(reg, skill_id)
        return skill

    def test_match_by_task_family(self) -> None:
        reg = SkillRegistry()
        self._setup_certified_skill(reg, "s1", scope="python_backend")
        self._setup_certified_skill(reg, "s2", scope="java_backend")

        matcher = SkillMatcher(reg)
        results = matcher.match("python_backend", "S1")
        ids = [s.skill_id for s in results]
        assert "s1" in ids
        assert "s2" not in ids

    def test_match_wildcard_scope(self) -> None:
        reg = SkillRegistry()
        self._setup_certified_skill(reg, "s1", scope="*")

        matcher = SkillMatcher(reg)
        results = matcher.match("anything", "S1")
        assert len(results) == 1

    def test_precondition_check_filters(self) -> None:
        reg = SkillRegistry()
        self._setup_certified_skill(
            reg,
            "s1",
            scope="*",
            preconditions=["task_family == 'python_backend'"],
        )

        matcher = SkillMatcher(reg)

        # Matching context
        results = matcher.match("*", "S1", context={"task_family": "python_backend"})
        assert len(results) == 1

        # Non-matching context
        results = matcher.match("*", "S1", context={"task_family": "java_backend"})
        assert len(results) == 0

    def test_forbidden_check_filters(self) -> None:
        reg = SkillRegistry()
        self._setup_certified_skill(
            reg,
            "s1",
            scope="*",
            forbidden=["dangerous_mode"],
        )

        matcher = SkillMatcher(reg)

        # No forbidden present
        results = matcher.match("*", "S1", context={"safe": True})
        assert len(results) == 1

        # Forbidden present
        results = matcher.match("*", "S1", context={"dangerous_mode": True})
        assert len(results) == 0

    def test_no_context_passes_all_conditions(self) -> None:
        reg = SkillRegistry()
        self._setup_certified_skill(
            reg,
            "s1",
            scope="*",
            preconditions=["some_key == 'val'"],
            forbidden=["bad_key"],
        )

        matcher = SkillMatcher(reg)
        results = matcher.match("*", "S1")  # No context
        assert len(results) == 1


# ---------------------------------------------------------------------------
# SkillUsageRecorder tests
# ---------------------------------------------------------------------------


class TestSkillUsageRecorder:
    def test_record_success(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate())
        recorder = SkillUsageRecorder(reg)

        recorder.record_usage("skill_abc", "run_100", success=True)

        skill = reg.get("skill_abc")
        assert skill is not None, f"Expected non-None result for skill"
        assert skill.success_count == 1
        assert skill.failure_count == 0
        assert skill.evidence_count == 2  # 1 original + 1 recorded
        assert "run_100" in skill.source_run_ids

    def test_record_failure(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate())
        recorder = SkillUsageRecorder(reg)

        recorder.record_usage("skill_abc", "run_100", success=False)

        skill = reg.get("skill_abc")
        assert skill is not None, f"Expected non-None result for skill"
        assert skill.failure_count == 1

    def test_record_missing_skill_raises(self) -> None:
        reg = SkillRegistry()
        recorder = SkillUsageRecorder(reg)

        with pytest.raises(KeyError):
            recorder.record_usage("no_such", "run_1", success=True)

    def test_get_usage_stats(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate())
        recorder = SkillUsageRecorder(reg)

        recorder.record_usage("skill_abc", "r1", success=True)
        recorder.record_usage("skill_abc", "r2", success=True)
        recorder.record_usage("skill_abc", "r3", success=False)

        stats = recorder.get_usage_stats("skill_abc")
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert stats["evidence_count"] == 4  # 1 original + 3
        assert abs(stats["success_rate"] - 2 / 3) < 0.01

    def test_get_usage_stats_missing_skill(self) -> None:
        reg = SkillRegistry()
        recorder = SkillUsageRecorder(reg)
        with pytest.raises(KeyError):
            recorder.get_usage_stats("nope")

    def test_get_run_skills(self) -> None:
        reg = SkillRegistry()
        reg.register_candidate(_make_candidate("s1"))
        reg.register_candidate(_make_candidate("s2"))
        recorder = SkillUsageRecorder(reg)

        recorder.record_usage("s1", "run_A", success=True)
        recorder.record_usage("s2", "run_A", success=True)
        recorder.record_usage("s1", "run_B", success=False)

        skills_a = recorder.get_run_skills("run_A")
        assert set(skills_a) == {"s1", "s2"}

        skills_b = recorder.get_run_skills("run_B")
        assert skills_b == ["s1"]

        assert recorder.get_run_skills("run_C") == []


# ---------------------------------------------------------------------------
# Full lifecycle integration test
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_candidate_to_certified_with_usage(self) -> None:
        """End-to-end: extract candidate, record usage, promote through lifecycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = SkillRegistry(storage_dir=tmpdir)
            recorder = SkillUsageRecorder(reg)

            # Step 1: Register candidate from evolve
            candidate = _make_candidate(evidence=1, run_ids=["run_001"])
            reg.register_candidate(candidate)
            skill = reg.get("skill_abc")
            assert skill is not None, f"Expected non-None result for skill"
            assert skill.lifecycle_stage == "candidate"

            # Step 2: Record usage to build evidence
            recorder.record_usage("skill_abc", "run_002", success=True)
            # Now evidence_count == 2

            # Step 3: Promote to provisional
            reg.promote("skill_abc", "provisional")
            assert skill.lifecycle_stage == "provisional"

            # Step 4: More usage
            for i in range(3, 7):
                recorder.record_usage("skill_abc", f"run_{i:03d}", success=(i != 5))
            # evidence = 2 + 4 = 6, success = 1 + 3 = 4, failure = 0 + 1 = 1
            # rate = 4/5 = 0.8

            # Step 5: Promote to certified
            reg.promote("skill_abc", "certified", evidence=["usage_data"])
            assert skill.lifecycle_stage == "certified"

            # Step 6: Verify matching
            matcher = SkillMatcher(reg)
            results = matcher.match("python_backend", "S3")
            assert any(s.skill_id == "skill_abc" for s in results)

            # Step 7: Persist and reload
            reg.save()
            reg2 = SkillRegistry(storage_dir=tmpdir)
            reg2.load()
            loaded = reg2.get("skill_abc")
            assert loaded is not None, f"Expected non-None result for loaded"
            assert loaded.lifecycle_stage == "certified"
            assert loaded.success_count == 4
            assert len(loaded.promotion_history) == 2

            # Step 8: Deprecate and retire
            reg2.deprecate("skill_abc", reason="Superseded")
            assert loaded.lifecycle_stage == "deprecated"
            reg2.retire("skill_abc")
            assert loaded.lifecycle_stage == "retired"

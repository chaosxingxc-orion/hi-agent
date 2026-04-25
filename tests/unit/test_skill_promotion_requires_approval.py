"""Unit: skill promotion is blocked by default until human approval is granted."""

from __future__ import annotations

import pytest
from hi_agent.evolve.contracts import PromotionBlockedError
from hi_agent.evolve.dataset_evaluator import DatasetEvaluator, SkillPromotionPipeline


class _Approved:
    """Minimal approval context that signals approval."""

    approved = True


class _NotApproved:
    """Minimal approval context that denies approval."""

    approved = False


def test_promotion_blocked_without_approval():
    """auto_promote=True + human_approval_required=True raises PromotionBlockedError by default."""
    pipeline = SkillPromotionPipeline(
        DatasetEvaluator(),
        auto_promote=True,
        human_approval_required=True,
    )
    with pytest.raises(PromotionBlockedError):
        pipeline.run([])


def test_promotion_blocked_with_denied_approval_context():
    """Explicit approved=False also raises PromotionBlockedError."""
    pipeline = SkillPromotionPipeline(
        DatasetEvaluator(),
        auto_promote=True,
        human_approval_required=True,
    )
    with pytest.raises(PromotionBlockedError):
        pipeline.run([], approval_context=_NotApproved())


def test_promotion_allowed_with_approved_context():
    """approved=True bypasses the human approval gate."""
    pipeline = SkillPromotionPipeline(
        DatasetEvaluator(),
        auto_promote=True,
        human_approval_required=True,
    )
    # No PromotionBlockedError — should return a result (no actual promotions with empty input)
    result = pipeline.run([], approval_context=_Approved())
    assert result is not None


def test_no_gate_when_human_approval_disabled():
    """human_approval_required=False bypasses the gate entirely."""
    pipeline = SkillPromotionPipeline(
        DatasetEvaluator(),
        auto_promote=True,
        human_approval_required=False,
    )
    result = pipeline.run([])
    assert result is not None


def test_no_gate_when_auto_promote_false():
    """auto_promote=False means the gate is never reached."""
    pipeline = SkillPromotionPipeline(
        DatasetEvaluator(),
        auto_promote=False,
        human_approval_required=True,
    )
    result = pipeline.run([])
    assert result is not None

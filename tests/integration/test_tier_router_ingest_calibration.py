"""Integration: TierRouter.ingest_calibration_signal is record-only.

Uses real TierRouter with no mocks on the SUT.
"""

from __future__ import annotations

from hi_agent.evolve.contracts import CalibrationSignal
from hi_agent.llm.registry import ModelRegistry
from hi_agent.llm.tier_router import TierRouter


def _make_router() -> TierRouter:
    return TierRouter(ModelRegistry())


def test_ingest_signal_appends_to_log():
    """ingest_calibration_signal stores the signal in _calibration_log."""
    router = _make_router()
    sig = CalibrationSignal(
        project_id="p1",
        run_id="r1",
        model="gpt-4",
        tier="strong",
        cost_usd=0.01,
        quality_score=0.9,
    )
    router.ingest_calibration_signal(sig)
    assert len(router._calibration_log) == 1
    assert router._calibration_log[0] is sig


def test_ingest_signal_does_not_change_routing():
    """ingest_calibration_signal must not modify tier routing (record-only in Wave 8)."""
    router = _make_router()
    initial_tier = router.get_tier_for_purpose("control")
    sig = CalibrationSignal(
        project_id="p1",
        run_id="r1",
        model="gpt-4",
        tier="tier_a",
        cost_usd=0.01,
        quality_score=0.9,
    )
    router.ingest_calibration_signal(sig)
    assert router.get_tier_for_purpose("control") == initial_tier


def test_ingest_multiple_signals():
    """Multiple signals accumulate in the log."""
    router = _make_router()
    for i in range(5):
        sig = CalibrationSignal(
            project_id="p1",
            run_id=f"r{i}",
            model="gpt-4",
            tier="medium",
        )
        router.ingest_calibration_signal(sig)
    assert len(router._calibration_log) == 5

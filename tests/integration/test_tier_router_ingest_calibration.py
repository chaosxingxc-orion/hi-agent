"""Integration: TierRouter.ingest_calibration_signal active calibration.

Uses real TierRouter with no mocks on the SUT.
"""

from __future__ import annotations

from hi_agent.evolve.contracts import CalibrationSignal
from hi_agent.llm.registry import ModelRegistry, ModelTier
from hi_agent.llm.tier_router import TierRouter


def _make_router() -> TierRouter:
    return TierRouter(ModelRegistry())


def _sig(tier: str, quality: float, run_id: str = "r1") -> CalibrationSignal:
    return CalibrationSignal(
        project_id="p1",
        run_id=run_id,
        model="gpt-4",
        tier=tier,
        quality_score=quality,
    )


def test_ingest_signal_appends_to_log():
    """ingest_calibration_signal stores the signal in _calibration_log."""
    router = _make_router()
    sig = _sig("strong", 0.9)
    router.ingest_calibration_signal(sig)
    assert len(router._calibration_log) == 1
    assert router._calibration_log[0] is sig


def test_insufficient_samples_no_routing_change():
    """Fewer than 3 samples must not change routing."""
    router = _make_router()
    initial_tier = router.get_tier_for_purpose("control")
    for i in range(2):
        router.ingest_calibration_signal(_sig("medium", 0.1, f"r{i}"))
    assert router.get_tier_for_purpose("control") == initial_tier


def test_unknown_tier_signal_ignored():
    """Signals with an unrecognized tier string are stored but ignored for calibration."""
    router = _make_router()
    initial = router.get_tier_for_purpose("control")
    for i in range(5):
        router.ingest_calibration_signal(_sig("tier_unknown", 0.0, f"r{i}"))
    assert router.get_tier_for_purpose("control") == initial


def test_ingest_multiple_signals():
    """Multiple signals accumulate in the log."""
    router = _make_router()
    for i in range(5):
        router.ingest_calibration_signal(_sig("medium", 0.5, f"r{i}"))
    assert len(router._calibration_log) == 5


def test_low_quality_signals_upgrade_tier():
    """3+ low-quality signals for a tier upgrade all purposes mapped to that tier."""
    router = _make_router()
    # "evaluation" and "compression" and "perception" map to LIGHT by default
    assert router.get_tier_for_purpose("perception") == ModelTier.LIGHT
    for i in range(3):
        router.ingest_calibration_signal(_sig(ModelTier.LIGHT, 0.3, f"r{i}"))
    # Purposes using LIGHT should be upgraded to MEDIUM
    assert router.get_tier_for_purpose("perception") == ModelTier.MEDIUM


def test_high_quality_signals_downgrade_tier():
    """3+ high-quality signals for STRONG tier downgrade purposes to MEDIUM."""
    router = _make_router()
    # "routing" maps to MEDIUM; set it to STRONG manually so we can test downgrade
    router.set_tier("routing", ModelTier.STRONG)
    assert router.get_tier_for_purpose("routing") == ModelTier.STRONG
    for i in range(3):
        router.ingest_calibration_signal(_sig(ModelTier.STRONG, 0.95, f"r{i}"))
    assert router.get_tier_for_purpose("routing") == ModelTier.MEDIUM


def test_medium_quality_signals_no_change():
    """Signals with quality in neutral range (0.60–0.88) leave routing unchanged."""
    router = _make_router()
    initial = router.get_tier_for_purpose("control")
    for i in range(5):
        router.ingest_calibration_signal(_sig(ModelTier.MEDIUM, 0.75, f"r{i}"))
    assert router.get_tier_for_purpose("control") == initial


def test_calibration_stats_window_capped_at_ten():
    """Sliding window holds at most 10 entries."""
    router = _make_router()
    for i in range(15):
        router.ingest_calibration_signal(_sig(ModelTier.MEDIUM, 0.5, f"r{i}"))
    assert len(router._calibration_stats.get(ModelTier.MEDIUM, [])) == 10

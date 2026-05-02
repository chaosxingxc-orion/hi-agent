"""Unit tests for TierRouter active calibration (P-7 closure)."""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.llm.registry import ModelRegistry, ModelTier
from hi_agent.llm.tier_router import (
    _CALIBRATION_MIN_SAMPLES,
    _CALIBRATION_WINDOW,
    _QUALITY_DOWNGRADE_THRESHOLD,
    _QUALITY_UPGRADE_THRESHOLD,
    TierRouter,
)


def _router() -> TierRouter:
    return TierRouter(ModelRegistry())


def _fake_signal(tier: str, quality: float) -> object:
    sig = MagicMock()
    sig.tier = tier
    sig.quality_score = quality
    return sig


class TestCalibrationConstants:
    def test_window_size_reasonable(self):
        assert 5 <= _CALIBRATION_WINDOW <= 50

    def test_thresholds_ordered(self):
        assert _QUALITY_UPGRADE_THRESHOLD < _QUALITY_DOWNGRADE_THRESHOLD

    def test_min_samples_at_least_three(self):
        assert _CALIBRATION_MIN_SAMPLES >= 3


class TestIngestSignalStorage:
    def test_signal_stored_in_log(self):
        router = _router()
        sig = _fake_signal("medium", 0.8)
        router.ingest_calibration_signal(sig)
        assert router._calibration_log[-1] is sig

    def test_quality_stored_in_stats(self):
        router = _router()
        router.ingest_calibration_signal(_fake_signal("medium", 0.75))
        assert router._calibration_stats["medium"] == [0.75]

    def test_unknown_tier_not_stored_in_stats(self):
        router = _router()
        router.ingest_calibration_signal(_fake_signal("unknown_tier", 0.5))
        assert "unknown_tier" not in router._calibration_stats

    def test_missing_tier_attr_safe(self):
        """Signals without tier attribute are stored but do not crash."""
        router = _router()
        sig = MagicMock(spec=[])  # no attributes
        router.ingest_calibration_signal(sig)
        assert router._calibration_log[-1] is sig

    def test_window_capped(self):
        router = _router()
        for _i in range(_CALIBRATION_WINDOW + 5):
            router.ingest_calibration_signal(_fake_signal("light", 0.5))
        assert len(router._calibration_stats["light"]) == _CALIBRATION_WINDOW


class TestUpgradeCalibration:
    def test_upgrade_fires_after_min_samples(self):
        router = _router()
        router.set_tier("perception", ModelTier.LIGHT)
        # Insufficient samples: no change
        for _i in range(_CALIBRATION_MIN_SAMPLES - 1):
            router.ingest_calibration_signal(_fake_signal(ModelTier.LIGHT, 0.1))
        assert router.get_tier_for_purpose("perception") == ModelTier.LIGHT
        # Exactly min_samples: triggers upgrade
        router.ingest_calibration_signal(_fake_signal(ModelTier.LIGHT, 0.1))
        assert router.get_tier_for_purpose("perception") == ModelTier.MEDIUM

    def test_upgrade_light_to_medium(self):
        router = _router()
        router.set_tier("evaluation", ModelTier.LIGHT)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.LIGHT, 0.0))
        assert router.get_tier_for_purpose("evaluation") == ModelTier.MEDIUM

    def test_upgrade_medium_to_strong(self):
        router = _router()
        router.set_tier("control", ModelTier.MEDIUM)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.MEDIUM, 0.0))
        assert router.get_tier_for_purpose("control") == ModelTier.STRONG

    def test_strong_cannot_upgrade_past_ceiling(self):
        router = _router()
        router.set_tier("analysis", ModelTier.STRONG)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.STRONG, 0.0))
        # STRONG is already the ceiling; mapping stays STRONG
        assert router.get_tier_for_purpose("analysis") == ModelTier.STRONG

    def test_allow_upgrade_false_respected(self):
        router = _router()
        router.set_tier("perception", ModelTier.LIGHT, allow_upgrade=False)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.LIGHT, 0.0))
        # allow_upgrade=False: must not upgrade
        assert router.get_tier_for_purpose("perception") == ModelTier.LIGHT


class TestDowngradeCalibration:
    def test_downgrade_fires_after_min_samples(self):
        router = _router()
        router.set_tier("routing", ModelTier.STRONG)
        for _i in range(_CALIBRATION_MIN_SAMPLES - 1):
            router.ingest_calibration_signal(_fake_signal(ModelTier.STRONG, 0.99))
        assert router.get_tier_for_purpose("routing") == ModelTier.STRONG
        router.ingest_calibration_signal(_fake_signal(ModelTier.STRONG, 0.99))
        assert router.get_tier_for_purpose("routing") == ModelTier.MEDIUM

    def test_downgrade_strong_to_medium(self):
        router = _router()
        router.set_tier("routing", ModelTier.STRONG)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.STRONG, 1.0))
        assert router.get_tier_for_purpose("routing") == ModelTier.MEDIUM

    def test_downgrade_medium_to_light(self):
        router = _router()
        router.set_tier("control", ModelTier.MEDIUM)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.MEDIUM, 1.0))
        assert router.get_tier_for_purpose("control") == ModelTier.LIGHT

    def test_light_cannot_downgrade_past_floor(self):
        router = _router()
        router.set_tier("evaluation", ModelTier.LIGHT)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.LIGHT, 1.0))
        # LIGHT is the floor; mapping stays LIGHT
        assert router.get_tier_for_purpose("evaluation") == ModelTier.LIGHT

    def test_allow_downgrade_false_respected(self):
        router = _router()
        router.set_tier("routing", ModelTier.STRONG, allow_downgrade=False)
        for _ in range(_CALIBRATION_MIN_SAMPLES):
            router.ingest_calibration_signal(_fake_signal(ModelTier.STRONG, 1.0))
        assert router.get_tier_for_purpose("routing") == ModelTier.STRONG


class TestNeutralZone:
    def test_neutral_quality_no_change(self):
        router = _router()
        initial = router.get_tier_for_purpose("control")
        for _ in range(_CALIBRATION_MIN_SAMPLES + 2):
            router.ingest_calibration_signal(_fake_signal(ModelTier.MEDIUM, 0.75))
        assert router.get_tier_for_purpose("control") == initial

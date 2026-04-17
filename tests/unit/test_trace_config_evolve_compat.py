"""Unit tests for TraceConfig evolve_mode field and backward-compat property (HI-W1-D2-001)."""

import warnings
from hi_agent.config.trace_config import TraceConfig


def test_new_evolve_mode_default_is_auto():
    cfg = TraceConfig()
    assert cfg.evolve_mode == "auto"


def test_old_evolve_enabled_property_emits_deprecation():
    cfg = TraceConfig()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _ = cfg.evolve_enabled
        assert any("evolve_enabled" in str(warning.message) for warning in w)

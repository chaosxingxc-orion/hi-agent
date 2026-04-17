"""Integration tests for runner-level evolve gating (HI-W1-D2-001).

These tests verify that the TraceConfig.evolve_mode field integrates correctly
with resolve_evolve_effective across representative runtime modes.  No internal
mocks are used — real component instances only.
"""

from hi_agent.config.trace_config import TraceConfig
from hi_agent.config.evolve_policy import resolve_evolve_effective


def test_default_auto_mode_in_dev_smoke_resolves_true():
    cfg = TraceConfig()  # default evolve_mode="auto"
    enabled, source = resolve_evolve_effective(cfg.evolve_mode, "dev-smoke")
    assert enabled is True
    assert source == "auto_dev_on"


def test_default_auto_mode_in_prod_real_resolves_false():
    cfg = TraceConfig()
    enabled, source = resolve_evolve_effective(cfg.evolve_mode, "prod-real")
    assert enabled is False
    assert source == "auto_prod_off"


def test_explicit_on_mode_resolves_true_in_prod():
    cfg = TraceConfig(evolve_mode="on")
    enabled, source = resolve_evolve_effective(cfg.evolve_mode, "prod-real")
    assert enabled is True
    assert source == "explicit_on"


def test_explicit_off_mode_resolves_false_in_dev():
    cfg = TraceConfig(evolve_mode="off")
    enabled, source = resolve_evolve_effective(cfg.evolve_mode, "dev-smoke")
    assert enabled is False
    assert source == "explicit_off"

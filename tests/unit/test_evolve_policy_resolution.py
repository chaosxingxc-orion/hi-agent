"""Unit tests for evolve policy resolution (HI-W1-D2-001)."""

import pytest
from hi_agent.config.evolve_policy import resolve_evolve_effective


@pytest.mark.parametrize(
    "mode,runtime_mode,expected_enabled,expected_source",
    [
        ("on", "dev-smoke", True, "explicit_on"),
        ("on", "local-real", True, "explicit_on"),
        ("on", "prod-real", True, "explicit_on"),
        ("off", "dev-smoke", False, "explicit_off"),
        ("off", "local-real", False, "explicit_off"),
        ("off", "prod-real", False, "explicit_off"),
        ("auto", "dev-smoke", True, "auto_dev_on"),
        ("auto", "local-real", False, "auto_prod_off"),
        ("auto", "prod-real", False, "auto_prod_off"),
    ],
)
def test_resolve_evolve_effective(mode, runtime_mode, expected_enabled, expected_source):
    enabled, source = resolve_evolve_effective(mode, runtime_mode)
    assert enabled == expected_enabled
    assert source == expected_source

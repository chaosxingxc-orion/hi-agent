"""Test that hi_agent.operations is the canonical namespace.

hi_agent.experiment (old name) must emit DeprecationWarning but still work.
"""
from __future__ import annotations

import warnings


def test_canonical_ops_import():
    """hi_agent.operations imports without DeprecationWarning."""
    import hi_agent.operations  # noqa: F401  expiry_wave: Wave 29


def test_deprecated_experiment_import_warns():
    """hi_agent.experiment emits DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import hi_agent.experiment  # noqa: F401  expiry_wave: Wave 29
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "Expected DeprecationWarning from hi_agent.experiment"
    assert "hi_agent.operations" in str(dep_warns[0].message)


def test_longrunningopstore_accessible_via_operations():
    """LongRunningOpStore is importable from hi_agent.operations."""
    from hi_agent.operations.op_store import LongRunningOpStore  # noqa: F401  expiry_wave: Wave 29

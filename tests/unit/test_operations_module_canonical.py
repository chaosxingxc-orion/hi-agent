"""Test that hi_agent.operations is the canonical namespace.

The legacy ``hi_agent.experiment`` shim was deleted in W34-F (W34-NAMING-CLOSE,
H-3'). This test now asserts both (a) the canonical package imports cleanly
and (b) the deprecated shim is gone.
"""
from __future__ import annotations

import importlib

import pytest


def test_canonical_ops_import():
    """hi_agent.operations imports without DeprecationWarning."""
    import hi_agent.operations  # noqa: F401  expiry_wave: permanent


def test_legacy_experiment_package_removed():
    """hi_agent.experiment (W11 shim) was deleted in W34-F.

    Importing it must raise ModuleNotFoundError. If this test fails the
    package was reintroduced and must be removed again.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hi_agent.experiment")


def test_longrunningopstore_accessible_via_operations():
    """LongRunningOpStore is importable from hi_agent.operations."""
    from hi_agent.operations.op_store import (
        LongRunningOpStore,  # noqa: F401  expiry_wave: permanent
    )

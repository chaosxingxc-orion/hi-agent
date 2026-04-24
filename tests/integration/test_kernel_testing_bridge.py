"""Tests for hi_agent.testing bridge exports."""

from __future__ import annotations

from hi_agent.testing import (
    InMemoryDedupeStore,
    InMemoryKernelRuntimeEventLog,
    StaticRecoveryGateService,
)


def test_testing_bridge_exports_are_importable() -> None:
    """Bridge module should expose kernel testing primitives."""
    assert InMemoryKernelRuntimeEventLog is not None
    assert InMemoryDedupeStore is not None
    assert StaticRecoveryGateService is not None


def test_testing_bridge_types_are_instantiable() -> None:
    """Exported test primitives should be constructable."""
    _ = InMemoryKernelRuntimeEventLog()
    _ = InMemoryDedupeStore()
    _ = StaticRecoveryGateService()

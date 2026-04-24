"""Tests for runtime_adapter package export surface."""

from __future__ import annotations

import hi_agent.runtime_adapter as runtime_adapter


def test_runtime_adapter_exports_kernel_facade_adapter() -> None:
    """KernelFacadeAdapter should be importable from package root."""
    assert isinstance(runtime_adapter.KernelFacadeAdapter, type)


def test_runtime_adapter_exports_temporal_health_symbols() -> None:
    """Temporal health helpers should be exposed on package root."""
    assert isinstance(runtime_adapter.TemporalConnectionState, type)
    assert isinstance(runtime_adapter.TemporalConnectionHealthReport, type)
    assert isinstance(runtime_adapter.TemporalConnectionHealthCheck, type)
    assert isinstance(runtime_adapter.TemporalConnectionProbeResult, type)
    assert callable(runtime_adapter.check_temporal_connection)

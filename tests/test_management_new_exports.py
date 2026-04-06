"""Tests for newly added management package exports."""

from __future__ import annotations

from hi_agent.management import (
    build_operational_signals,
    cmd_runtime_config_get,
    cmd_runtime_config_history,
    cmd_runtime_config_patch,
    secure_cmd_gate_resolve,
)


def test_management_new_exports_are_callable() -> None:
    """Newly integrated management exports should be available and callable."""
    assert callable(build_operational_signals)
    assert callable(secure_cmd_gate_resolve)
    assert callable(cmd_runtime_config_get)
    assert callable(cmd_runtime_config_patch)
    assert callable(cmd_runtime_config_history)

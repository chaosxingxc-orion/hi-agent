"""Tests for management package exports."""

from __future__ import annotations

import hi_agent.management as management


def test_management_exports_include_gate_command_helpers() -> None:
    """Gate command helper exports should be present and callable."""
    assert callable(management.cmd_gate_list)
    assert callable(management.cmd_gate_list_pending)
    assert callable(management.cmd_gate_operational_signal)
    assert callable(management.cmd_gate_resolve)
    assert callable(management.cmd_gate_status)


def test_management_exports_include_runtime_config_symbols() -> None:
    """Runtime config symbols should be exported from package root."""
    assert isinstance(management.RuntimeConfigManager, type)
    assert isinstance(management.RuntimeConfigSnapshot, type)
    assert isinstance(management.RuntimeConfigStore, type)
    assert callable(management.patch_runtime_config)


def test_management_exports_include_config_history_symbols() -> None:
    """Config history symbols should be exported from package root."""
    assert isinstance(management.ConfigHistory, type)
    assert isinstance(management.ConfigHistoryEntry, type)

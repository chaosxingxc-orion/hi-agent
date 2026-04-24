"""Consolidated from three round-based files; tests management export capability.

Verifies that all management package exports are present and callable.
"""

from __future__ import annotations

import hi_agent.management as management
from hi_agent.management import (
    build_incident_runbook,
    build_operational_signals,
    cmd_ops_build_report,
    cmd_ops_build_runbook,
    cmd_runtime_config_get,
    cmd_runtime_config_history,
    cmd_runtime_config_patch,
    secure_cmd_gate_resolve,
)


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


def test_management_exports_include_runbook_and_ops_report_commands() -> None:
    """New runbook and ops report helpers should be package-exported."""
    assert callable(build_incident_runbook)
    assert callable(cmd_ops_build_report)
    assert callable(cmd_ops_build_runbook)


def test_management_new_exports_are_callable() -> None:
    """Newly integrated management exports should be available and callable."""
    assert callable(build_operational_signals)
    assert callable(secure_cmd_gate_resolve)
    assert callable(cmd_runtime_config_get)
    assert callable(cmd_runtime_config_patch)
    assert callable(cmd_runtime_config_history)

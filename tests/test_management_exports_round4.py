"""Round-4 export surface checks for management package."""

from __future__ import annotations

from hi_agent.management import (
    build_incident_runbook,
    cmd_ops_build_report,
    cmd_ops_build_runbook,
)


def test_management_exports_include_runbook_and_ops_report_commands() -> None:
    """New runbook and ops report helpers should be package-exported."""
    assert callable(build_incident_runbook)
    assert callable(cmd_ops_build_report)
    assert callable(cmd_ops_build_runbook)

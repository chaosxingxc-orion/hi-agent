"""Round-2 package export surface checks."""

from __future__ import annotations

from hi_agent import auth, management, route_engine, runtime_adapter


def test_auth_exports_include_command_context_symbols() -> None:
    """Auth package should export command-context builders/types."""
    assert hasattr(auth, "CommandAuthContext")
    assert hasattr(auth, "CommandContextError")
    assert hasattr(auth, "InvalidClaimError")
    assert hasattr(auth, "MissingContextClaimError")
    assert callable(auth.build_command_context_from_claims)


def test_management_exports_include_new_ops_symbols() -> None:
    """Management package should export dashboard/slo/secure/config commands."""
    assert callable(management.build_operational_signals)
    assert callable(management.build_operational_dashboard_payload)
    assert callable(management.evaluate_operational_alerts)
    assert callable(management.secure_cmd_gate_resolve)
    assert callable(management.cmd_runtime_config_get)
    assert callable(management.cmd_runtime_config_patch)
    assert callable(management.cmd_runtime_config_history)
    assert callable(management.build_slo_snapshot)
    assert hasattr(management, "SLOSnapshot")


def test_route_engine_and_runtime_adapter_exports_include_new_helpers() -> None:
    """Route/runtime packages should export audit and summary helpers."""
    assert callable(route_engine.record_route_decision_audit)
    assert callable(route_engine.is_low_confidence)
    assert callable(runtime_adapter.summarize_runtime_events)

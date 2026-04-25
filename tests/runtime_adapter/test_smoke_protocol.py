"""Smoke test: hi_agent.runtime_adapter.protocol importable and structurally valid."""

import pytest


@pytest.mark.smoke
def test_runtime_adapter_protocol_importable():
    """RuntimeAdapter Protocol can be imported without error."""
    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    assert RuntimeAdapter is not None


@pytest.mark.smoke
def test_runtime_adapter_has_mode_attribute():
    """RuntimeAdapter protocol defines a 'mode' property."""

    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    assert hasattr(RuntimeAdapter, "mode")


@pytest.mark.smoke
def test_runtime_adapter_has_required_methods():
    """RuntimeAdapter protocol defines all 17 required lifecycle methods."""
    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    required_methods = [
        "open_stage",
        "mark_stage_state",
        "record_task_view",
        "bind_task_view_to_decision",
        "start_run",
        "cancel_run",
        "resume_run",
        "signal_run",
        "open_branch",
        "mark_branch_state",
        "open_human_gate",
        "submit_approval",
        "spawn_child_run",
    ]
    for method in required_methods:
        assert hasattr(RuntimeAdapter, method), f"RuntimeAdapter missing method: {method}"

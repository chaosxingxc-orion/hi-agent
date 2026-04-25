"""Track D: /runs/{id}/reasoning-trace and /runs/{id}/gate_decision enforce run ownership."""
from __future__ import annotations

import inspect


def test_reasoning_trace_assigns_ctx():
    """handle_reasoning_trace must assign require_tenant_context() result to ctx."""
    from hi_agent.server.routes_runs import handle_reasoning_trace

    src = inspect.getsource(handle_reasoning_trace)
    assert "ctx = require_tenant_context()" in src, (
        "handle_reasoning_trace must assign ctx = require_tenant_context()"
    )


def test_reasoning_trace_calls_get_run_with_workspace():
    """handle_reasoning_trace must call get_run(workspace=ctx) for ownership check."""
    from hi_agent.server.routes_runs import handle_reasoning_trace

    src = inspect.getsource(handle_reasoning_trace)
    assert "workspace=ctx" in src, (
        "handle_reasoning_trace must call manager.get_run(run_id, workspace=ctx)"
    )


def test_reasoning_trace_returns_not_found():
    """handle_reasoning_trace must return 404 for unowned run."""
    from hi_agent.server.routes_runs import handle_reasoning_trace

    src = inspect.getsource(handle_reasoning_trace)
    assert "not_found" in src, (
        "handle_reasoning_trace must return 404 for unowned/unknown run"
    )


def test_gate_decision_assigns_ctx():
    """handle_gate_decision must assign require_tenant_context() result to ctx."""
    from hi_agent.server.routes_runs import handle_gate_decision

    src = inspect.getsource(handle_gate_decision)
    assert "ctx = require_tenant_context()" in src, (
        "handle_gate_decision must assign ctx = require_tenant_context()"
    )


def test_gate_decision_calls_get_run_with_workspace():
    """handle_gate_decision must call get_run(workspace=ctx) for ownership check."""
    from hi_agent.server.routes_runs import handle_gate_decision

    src = inspect.getsource(handle_gate_decision)
    assert "workspace=ctx" in src, (
        "handle_gate_decision must call manager.get_run(run_id, workspace=ctx)"
    )


def test_gate_decision_returns_not_found():
    """handle_gate_decision must return 404 for unowned run."""
    from hi_agent.server.routes_runs import handle_gate_decision

    src = inspect.getsource(handle_gate_decision)
    assert "not_found" in src, (
        "handle_gate_decision must return 404 for unowned/unknown run"
    )

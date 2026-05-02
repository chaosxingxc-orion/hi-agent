"""Unit tests for the Wave 11 RunExecutionContext seed."""
from __future__ import annotations

from hi_agent.context.run_execution_context import RunExecutionContext


def test_default_construction_is_all_empty_strings():
    ctx = RunExecutionContext()
    assert ctx.tenant_id == ""
    assert ctx.run_id == ""
    assert ctx.stage_id == ""


def test_to_spine_kwargs_returns_four_field_subset():
    ctx = RunExecutionContext(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        project_id="p1",
        run_id="r1",
        stage_id="stage_a",
    )
    spine = ctx.to_spine_kwargs()
    assert spine == {
        "tenant_id": "t1",
        "user_id": "u1",
        "session_id": "s1",
        "project_id": "p1",
    }


def test_with_stage_returns_new_instance_bound_to_stage():
    ctx = RunExecutionContext(tenant_id="t1", run_id="r1", stage_id="a")
    next_ctx = ctx.with_stage("b")
    assert next_ctx.stage_id == "b"
    assert next_ctx.run_id == "r1"
    assert ctx.stage_id == "a"


def test_with_capability_returns_new_instance_bound_to_capability():
    ctx = RunExecutionContext(tenant_id="t1", run_id="r1", capability_name="search")
    next_ctx = ctx.with_capability("synthesize")
    assert next_ctx.capability_name == "synthesize"
    assert ctx.capability_name == "search"


def test_frozen_prevents_mutation():
    ctx = RunExecutionContext(tenant_id="t1")
    try:
        ctx.tenant_id = "t2"  # type: ignore[misc]  expiry_wave: Wave 29
    except (AttributeError, Exception):
        return
    raise AssertionError("RunExecutionContext should be frozen")

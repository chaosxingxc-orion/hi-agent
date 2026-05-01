"""Unit tests for Wave 10.3 W3-D: RunExecutionContext pilot extensions.

Tests cover:
  - to_spine_kwargs_full() returns all 10 fields as strings
  - from_managed_run() correctly copies available fields from ManagedRun
  - from_managed_run().to_spine_kwargs() returns correct 4-field dict
"""
from __future__ import annotations

import dataclasses

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.run_manager import ManagedRun


def _make_managed_run(**overrides) -> ManagedRun:
    defaults = {
        "run_id": "run-test-001",
        "task_contract": {"task_id": "t1", "project_id": "proj-alpha"},
        "tenant_id": "tenant-acme",
        "user_id": "user-bob",
        "session_id": "sess-xyz",
    }
    defaults.update(overrides)
    return ManagedRun(**defaults)


class TestToSpineKwargsFull:
    def test_returns_all_ten_fields(self):
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
            profile_id="prof1",
            run_id="r1",
            parent_run_id="r0",
            stage_id="stage_a",
            capability_name="search",
            request_id="req-42",
        )
        full = ctx.to_spine_kwargs_full()
        assert full == {
            "tenant_id": "t1",
            "user_id": "u1",
            "session_id": "s1",
            "project_id": "p1",
            "profile_id": "prof1",
            "run_id": "r1",
            "parent_run_id": "r0",
            "stage_id": "stage_a",
            "capability_name": "search",
            "request_id": "req-42",
        }

    def test_returns_empty_strings_for_unset_fields(self):
        ctx = RunExecutionContext(run_id="r99")
        full = ctx.to_spine_kwargs_full()
        assert full["tenant_id"] == ""
        assert full["user_id"] == ""
        assert full["run_id"] == "r99"
        assert full["stage_id"] == ""
        assert full["request_id"] == ""

    def test_all_values_are_str_type(self):
        ctx = RunExecutionContext(
            tenant_id="t1",
            run_id="r1",
            capability_name="cap",
        )
        full = ctx.to_spine_kwargs_full()
        for key, val in full.items():
            assert isinstance(val, str), f"Field {key!r} should be str, got {type(val)}"

    def test_full_superset_of_to_spine_kwargs(self):
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
            run_id="r1",
        )
        spine4 = ctx.to_spine_kwargs()
        full = ctx.to_spine_kwargs_full()
        for k, v in spine4.items():
            assert full[k] == v, f"Mismatch on field {k!r}"


class TestFromManagedRun:
    def test_copies_all_available_spine_fields(self):
        run = _make_managed_run()
        ctx = RunExecutionContext.from_managed_run(run)
        assert ctx.tenant_id == "tenant-acme"
        assert ctx.user_id == "user-bob"
        assert ctx.session_id == "sess-xyz"
        assert ctx.project_id == "proj-alpha"
        assert ctx.run_id == "run-test-001"

    def test_optional_fields_default_to_empty_string(self):
        run = _make_managed_run()
        ctx = RunExecutionContext.from_managed_run(run)
        assert ctx.profile_id == ""
        assert ctx.parent_run_id == ""
        assert ctx.stage_id == ""
        assert ctx.capability_name == ""
        assert ctx.request_id == ""

    def test_to_spine_kwargs_matches_manual_construction(self):
        run = _make_managed_run()
        ctx_from_run = RunExecutionContext.from_managed_run(run)
        ctx_manual = RunExecutionContext(
            tenant_id="tenant-acme",
            user_id="user-bob",
            session_id="sess-xyz",
            project_id="proj-alpha",
            run_id="run-test-001",
        )
        assert ctx_from_run.to_spine_kwargs() == ctx_manual.to_spine_kwargs()

    def test_handles_missing_optional_attrs_gracefully(self):
        """from_managed_run must not raise if ManagedRun lacks optional attrs."""
        run = _make_managed_run()
        # Simulate a ManagedRun with no tenant_id (e.g., a replayed run skeleton)
        run_no_tenant = dataclasses.replace(run, tenant_id="")
        ctx = RunExecutionContext.from_managed_run(run_no_tenant)
        assert ctx.tenant_id == ""
        assert ctx.run_id == "run-test-001"

    def test_result_is_frozen(self):
        run = _make_managed_run()
        ctx = RunExecutionContext.from_managed_run(run)
        with pytest.raises((AttributeError, Exception)):
            ctx.tenant_id = "mutated"  # type: ignore[misc]  expiry_wave: Wave 29

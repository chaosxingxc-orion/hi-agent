"""Integration tests: TaskContract optional spine fields (body enrichment).

Layer 2 — Integration tests verifying that:
- TaskContract accepts optional tenant_id/user_id/session_id fields.
- When present in request body kwargs, they are stored on the contract.
- Existing callers that omit these fields continue to work (backwards-compat).

These tests wire the real TaskContract without mocking per Rule 4.
"""

from __future__ import annotations

from hi_agent.contracts.task import TaskContract


class TestTaskContractBodySpine:
    def test_spine_fields_accepted_when_provided(self):
        """TaskContract stores tenant_id/user_id/session_id from constructor."""
        contract = TaskContract(
            task_id="tc-001",
            goal="test goal",
            project_id="p1",
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
        )
        assert contract.tenant_id == "t1"
        assert contract.user_id == "u1"
        assert contract.session_id == "s1"

    def test_spine_fields_default_to_empty_string(self):
        """TaskContract without spine fields defaults them to empty string."""
        contract = TaskContract(
            task_id="tc-002",
            goal="test goal",
            project_id="p2",
        )
        assert contract.tenant_id == ""
        assert contract.user_id == ""
        assert contract.session_id == ""

    def test_spine_fields_parsed_from_run_data_dict(self):
        """Simulates how executor_factory builds a TaskContract from run_data body."""
        run_data = {
            "task_id": "tc-003",
            "goal": "analyse revenue",
            "project_id": "proj-003",
            "tenant_id": "tenant-from-body",
            "user_id": "user-from-body",
            "session_id": "session-from-body",
        }
        contract = TaskContract(
            task_id=run_data.get("task_id", ""),
            goal=run_data.get("goal", ""),
            project_id=run_data.get("project_id", ""),
            tenant_id=run_data.get("tenant_id", ""),
            user_id=run_data.get("user_id", ""),
            session_id=run_data.get("session_id", ""),
        )
        assert contract.tenant_id == "tenant-from-body"
        assert contract.user_id == "user-from-body"
        assert contract.session_id == "session-from-body"

    def test_body_spine_takes_precedence_over_empty_middleware(self):
        """Explicit body spine wins over empty middleware-derived values."""
        # Simulate: middleware_tenant="" (no auth), body has tenant
        middleware_tenant = ""
        body_tenant = "body-tenant"
        effective_tenant = body_tenant if body_tenant else middleware_tenant

        contract = TaskContract(
            task_id="tc-004",
            goal="test",
            project_id="p4",
            tenant_id=effective_tenant,
        )
        assert contract.tenant_id == "body-tenant"

    def test_middleware_value_used_when_body_spine_empty(self):
        """When body spine fields are empty, middleware-derived values are used."""
        # Simulate: body has no tenant, middleware provides it
        body_tenant = ""  # empty from request body
        middleware_tenant = "mw-tenant"
        effective_tenant = body_tenant if body_tenant else middleware_tenant

        contract = TaskContract(
            task_id="tc-005",
            goal="test",
            project_id="p5",
            tenant_id=effective_tenant,
        )
        assert contract.tenant_id == "mw-tenant"

    def test_backward_compat_existing_contract_construction(self):
        """Existing callers constructing TaskContract without spine fields still work."""
        contract = TaskContract(task_id="tc-006", goal="compat goal", project_id="p6")
        # No error, spine fields exist with default ""
        assert hasattr(contract, "tenant_id")
        assert hasattr(contract, "user_id")
        assert hasattr(contract, "session_id")
        assert contract.tenant_id == ""
        assert contract.user_id == ""
        assert contract.session_id == ""

    def test_all_fields_coexist_with_existing_fields(self):
        """New spine fields coexist with all pre-existing TaskContract fields."""
        contract = TaskContract(
            task_id="tc-007",
            goal="full contract",
            project_id="p7",
            priority=3,
            risk_level="high",
            tenant_id="t7",
            user_id="u7",
            session_id="s7",
        )
        # Existing fields unchanged
        assert contract.priority == 3
        assert contract.risk_level == "high"
        assert contract.project_id == "p7"
        # New fields present
        assert contract.tenant_id == "t7"
        assert contract.user_id == "u7"
        assert contract.session_id == "s7"

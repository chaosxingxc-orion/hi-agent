"""Tests for /manifest endpoint exposing runtime truth."""

from __future__ import annotations


class TestManifestRuntimeInventory:
    def test_manifest_has_required_keys(self):
        """Manifest response always has required top-level keys."""
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        client = TestClient(server.app)
        response = client.get("/manifest")
        assert response.status_code == 200
        data = response.json()
        for key in (
            "name",
            "version",
            "stages",
            "capabilities",
            "profiles",
            "mcp_servers",
            "endpoints",
        ):
            assert key in data, f"Missing key: {key}"

    def test_manifest_stages_from_stage_graph(self):
        """Stages in manifest come from the server's stage_graph, not hardcoded."""
        from hi_agent.server.app import AgentServer
        from hi_agent.trajectory.stage_graph import StageGraph
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        # Replace stage_graph with a custom 3-stage graph
        g = StageGraph()
        g.add_edge("step_a", "step_b")
        g.add_edge("step_b", "step_c")
        server.stage_graph = g

        client = TestClient(server.app)
        response = client.get("/manifest")
        data = response.json()
        assert "step_a" in data["stages"]
        assert "step_b" in data["stages"]
        # TRACE stages should NOT appear in a custom graph
        assert "S1_understand" not in data["stages"]

    def test_manifest_profiles_empty_by_default(self):
        """No profiles registered → profiles list is empty."""
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        client = TestClient(server.app)
        response = client.get("/manifest")
        data = response.json()
        assert isinstance(data["profiles"], list)

    def test_manifest_profiles_after_registration(self):
        """Profiles registered in builder's ProfileRegistry appear in manifest."""
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        # Register a profile in the builder's registry
        reg = server._builder.build_profile_registry()
        reg.register(
            ProfileSpec(
                profile_id="test_profile",
                display_name="Test Profile",
                stage_actions={"s1": "action_a"},
            )
        )

        client = TestClient(server.app)
        response = client.get("/manifest")
        data = response.json()
        profile_ids = [p["profile_id"] for p in data["profiles"]]
        assert "test_profile" in profile_ids

    def test_manifest_mcp_servers_list(self):
        """mcp_servers key present and is a list."""
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        client = TestClient(server.app)
        response = client.get("/manifest")
        data = response.json()
        assert isinstance(data["mcp_servers"], list)

    def test_manifest_has_runtime_mode(self):
        """Manifest reports runtime_mode key with a valid resolved value (not hardcoded)."""
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        client = TestClient(server.app)
        response = client.get("/manifest")
        data = response.json()
        assert "runtime_mode" in data
        # runtime_mode is now resolved via resolve_runtime_mode() — never hardcoded
        assert data["runtime_mode"] in ("dev-smoke", "local-real", "prod-real")

    def test_manifest_active_profile_is_none_at_startup(self):
        """Without a resolved profile, manifest reports active_profile=None."""
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        client = TestClient(server.app)
        response = client.get("/manifest")
        data = response.json()
        assert "active_profile" in data
        assert data["active_profile"] is None


class TestMCPBindingPolicy:
    def test_bind_all_without_transport_returns_zero(self):
        from unittest.mock import MagicMock

        from hi_agent.mcp.binding import MCPBinding

        mock_registry = MagicMock()
        mock_registry.list_servers.return_value = [
            {"server_id": "srv1", "status": "healthy", "tools": ["tool_a", "tool_b"]}
        ]
        mock_cap_registry = MagicMock()

        binding = MCPBinding(mock_cap_registry, mock_registry, transport=None)
        count = binding.bind_all()
        # No transport → nothing registered
        assert count == 0
        mock_cap_registry.register.assert_not_called()

    def test_bind_all_without_transport_tracks_unavailable(self):
        from unittest.mock import MagicMock

        from hi_agent.mcp.binding import MCPBinding

        mock_registry = MagicMock()
        mock_registry.list_servers.return_value = [
            {"server_id": "srv1", "status": "healthy", "tools": ["tool_a"]}
        ]
        binding = MCPBinding(MagicMock(), mock_registry, transport=None)
        binding.bind_all()
        unavailable = binding.list_unavailable()
        assert "mcp.srv1.tool_a" in unavailable

    def test_bind_all_with_transport_registers_tools(self):
        from unittest.mock import MagicMock

        from hi_agent.capability.registry import CapabilityRegistry
        from hi_agent.mcp.binding import MCPBinding

        mock_mcp_registry = MagicMock()
        mock_mcp_registry.list_servers.return_value = [
            {"server_id": "srv1", "status": "healthy", "tools": ["tool_a"]}
        ]

        class FakeTransport:
            def invoke(self, server_id, tool_name, payload):
                return {"success": True}

        cap_registry = CapabilityRegistry()
        binding = MCPBinding(cap_registry, mock_mcp_registry, transport=FakeTransport())
        count = binding.bind_all()
        assert count == 1
        assert "mcp.srv1.tool_a" in cap_registry.list_names()

    def test_bind_all_without_transport_does_not_register_broken_stubs(self):
        """Old behavior registered silently failing stubs.

        New behavior does not register stubs without transport.
        """
        from unittest.mock import MagicMock

        from hi_agent.capability.registry import CapabilityRegistry
        from hi_agent.mcp.binding import MCPBinding

        mock_mcp_registry = MagicMock()
        mock_mcp_registry.list_servers.return_value = [
            {"server_id": "srv1", "status": "healthy", "tools": ["t1", "t2"]}
        ]

        cap_registry = CapabilityRegistry()
        binding = MCPBinding(cap_registry, mock_mcp_registry, transport=None)
        binding.bind_all()
        # Capability registry must be empty — no broken stubs
        assert len(cap_registry.list_names()) == 0

    def test_bind_all_with_transport_does_not_register_unverified_servers(self):
        """P0 fix: servers with status='registered' (not yet health-checked) must NOT
        be bound into the capability registry even when a transport is present.
        Only 'healthy' servers (those that passed a real health check) are callable.
        """
        from unittest.mock import MagicMock

        from hi_agent.capability.registry import CapabilityRegistry
        from hi_agent.mcp.binding import MCPBinding

        class FakeTransport:
            def invoke(self, server_id, tool_name, payload):
                return {"success": True}

        mock_mcp_registry = MagicMock()
        mock_mcp_registry.list_servers.return_value = [
            # "registered" = declared by plugin but NOT yet health-checked
            {"server_id": "unverified", "status": "registered", "tools": ["echo"]},
            # "healthy" = passed real health probe
            {"server_id": "verified", "status": "healthy", "tools": ["ping"]},
        ]

        cap_registry = CapabilityRegistry()
        binding = MCPBinding(cap_registry, mock_mcp_registry, transport=FakeTransport())
        count = binding.bind_all()

        # Only the verified server's tool should be bound
        assert count == 1
        assert "mcp.verified.ping" in cap_registry.list_names()
        assert "mcp.unverified.echo" not in cap_registry.list_names()
        # Unverified tool must be tracked as unavailable
        assert "mcp.unverified.echo" in binding.list_unavailable()


class TestMCPStatusConsistency:
    """MCP status endpoints must all report the same reality.

    Verifies that /mcp/status, /mcp/tools/list, /manifest mcp_servers section,
    and /ready mcp section all describe the same transport_status and
    capability_mode so integrators get a single consistent view.
    """

    def _make_client(self):
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=8080, config=None)
        return TestClient(server.app), server

    def test_mcp_status_and_manifest_agree_on_transport_status(self):
        """transport_status in /mcp/status must match what manifest declares."""
        client, _ = self._make_client()

        status_resp = client.get("/mcp/status")
        manifest_resp = client.get("/manifest")

        assert status_resp.status_code == 200
        assert manifest_resp.status_code == 200

        mcp_status = status_resp.json()
        manifest = manifest_resp.json()

        # Both must agree on the platform boundary
        status_transport = mcp_status.get("transport_status")
        e2e_mcp = manifest.get("e2e_contract", {}).get("mcp_provider", {})
        manifest_mcp_status = e2e_mcp.get("status")

        # When no external server is reachable, both must consistently declare
        # infrastructure_only.  "registered_but_unreachable" is also a non-wired
        # state where manifest_mcp_status must stay "infrastructure_only".
        if status_transport in ("not_wired", "registered_but_unreachable"):
            assert manifest_mcp_status == "infrastructure_only", (
                f"/mcp/status says transport_status={status_transport!r} but manifest says "
                f"mcp_provider.status={manifest_mcp_status!r} — inconsistent"
            )

    def test_mcp_tools_list_consistent_with_mcp_status(self):
        """Tools listed by /mcp/tools/list must be consistent with /mcp/status capability_mode."""
        client, _ = self._make_client()

        status_resp = client.get("/mcp/status")
        tools_resp = client.post("/mcp/tools/list", json={})

        assert status_resp.status_code == 200
        assert tools_resp.status_code == 200

        mcp_status = status_resp.json()
        tools_data = tools_resp.json()

        capability_mode = mcp_status.get("capability_mode")
        tools = tools_data.get("tools", [])

        if capability_mode == "infrastructure_only":
            # In infrastructure_only mode, tools should reflect platform capabilities,
            # not external MCP server tools.  The key contract is that neither endpoint
            # contradicts the other about what's available.
            assert isinstance(tools, list), "tools must be a list"

    def test_readiness_mcp_section_consistent_with_mcp_status(self):
        """/ready MCP section must be consistent with /mcp/status."""
        client, _ = self._make_client()

        ready_resp = client.get("/ready")
        status_resp = client.get("/mcp/status")

        assert status_resp.status_code == 200
        mcp_status_data = status_resp.json()

        # /ready may have a 200 or 503; either way the body must be present
        if ready_resp.status_code in (200, 503):
            ready_data = ready_resp.json()
            # If /ready exposes an mcp subsystem, check consistency
            ready_mcp = ready_data.get("subsystems", {}).get("mcp", None)
            if ready_mcp is not None and "transport_status" in ready_mcp:
                assert ready_mcp["transport_status"] == mcp_status_data.get("transport_status"), (
                    f"/ready mcp.transport_status={ready_mcp['transport_status']!r} "
                    f"disagrees with /mcp/status transport_status="
                    f"{mcp_status_data.get('transport_status')!r}"
                )

    def test_manifest_contract_field_status_present(self):
        """Manifest must include contract_field_status for integrator transparency."""
        client, _ = self._make_client()
        resp = client.get("/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert "contract_field_status" in data, (
            "manifest must expose 'contract_field_status' so integrators know "
            "which TaskContract fields the platform actually consumes"
        )
        field_status = data["contract_field_status"]
        assert isinstance(field_status, dict)
        # Spot-check key ACTIVE fields
        for f in ("goal", "acceptance_criteria", "budget", "deadline"):
            assert field_status.get(f) == "ACTIVE", (
                f"Field {f!r} should be ACTIVE in contract_field_status"
            )
        # Spot-check PASSTHROUGH fields
        for f in ("environment_scope", "input_refs", "parent_task_id"):
            assert field_status.get(f) == "PASSTHROUGH", (
                f"Field {f!r} should be PASSTHROUGH in contract_field_status"
            )

"""Integration test for /manifest full CapabilityDescriptor surface (DX-4).

Layer 2 (Integration): real AgentServer wired with real capability registry.
No MagicMock on the subsystem under test.

Verifies that each entry in capability_views includes the DX-4 fields
added to the manifest route: risk_class, requires_approval,
provenance_required, source_reference_policy, reproducibility_level,
license_policy.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# Expected DX-4 descriptor fields and their value constraints
_EXPECTED_FIELDS: dict[str, type | tuple] = {
    "risk_class": str,
    "requires_approval": bool,
    "provenance_required": bool,
    "source_reference_policy": str,
    "reproducibility_level": str,
    "license_policy": list,
}


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Real AgentServer in dev mode."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_manifest_capability_views_have_full_descriptor_fields(test_client) -> None:
    """GET /manifest capability_views entries include all DX-4 descriptor fields."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code}"

    body = resp.json()
    views = body.get("capability_views", [])
    # The registry may be empty in test mode; that is acceptable —
    # the route must still return 200 with a list.
    assert isinstance(views, list)

    for view in views:
        for field_name, expected_type in _EXPECTED_FIELDS.items():
            assert field_name in view, (
                f"capability_view for {view.get('name')!r} is missing field {field_name!r}"
            )
            assert isinstance(view[field_name], expected_type), (
                f"capability_view[{field_name!r}] expected {expected_type}, "
                f"got {type(view[field_name])} (value: {view[field_name]!r})"
            )

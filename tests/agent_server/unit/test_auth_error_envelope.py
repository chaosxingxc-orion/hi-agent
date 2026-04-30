"""HD-5 (W24-J5): unified error envelope across agent_server.

Verifies that:
1. ``ErrorCategory`` (hi_agent.server.error_categories) exposes
   ``AUTH_REQUIRED`` so the boundary can speak in shared category names.
2. ``AuthError.to_envelope`` returns the canonical four-field shape.
3. ``TenantContextMiddleware`` returns the same envelope on 401.
"""

from __future__ import annotations

from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.contracts.errors import AuthError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hi_agent.server.error_categories import ErrorCategory


def test_error_category_includes_auth_required() -> None:
    """ErrorCategory enum exposes AUTH_REQUIRED (HD-5)."""
    assert ErrorCategory.AUTH_REQUIRED.value == "auth_required"


def test_auth_error_to_envelope_shape() -> None:
    """AuthError.to_envelope returns the canonical four-field envelope."""
    err = AuthError("missing or empty X-Tenant-Id header", tenant_id="", detail="")
    envelope = err.to_envelope()
    assert envelope["error_category"] == "auth_required"
    assert envelope["message"] == "missing or empty X-Tenant-Id header"
    assert envelope["retryable"] is False
    assert envelope["next_action"] == "supply X-Tenant-Id header"


def test_tenant_context_middleware_returns_unified_envelope() -> None:
    """A request without X-Tenant-Id receives the structured 401 envelope."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/probe")
    async def probe() -> dict[str, str]:  # pragma: no cover - never reached
        return {"ok": "true"}

    client = TestClient(app)
    resp = client.get("/probe")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_category"] == "auth_required"
    assert body["retryable"] is False
    assert body["next_action"] == "supply X-Tenant-Id header"
    assert "X-Tenant-Id" in body["message"]


def test_tenant_context_middleware_passes_when_header_present() -> None:
    """A request with X-Tenant-Id passes through to the handler."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/probe")
    async def probe() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app)
    resp = client.get("/probe", headers={"X-Tenant-Id": "tenant-A"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": "true"}

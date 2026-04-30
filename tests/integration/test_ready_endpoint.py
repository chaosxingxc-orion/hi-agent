"""Integration test: GET /ready must return 200 without recursion.

Layer 2 (Integration): real SystemBuilder + real ReadinessProbe wired together.
Zero mocks on the subsystem under test.

Covers:
- GET /ready returns 200 in <2s (no RecursionError from build_capability_registry
  calling self.readiness() which calls build_invoker() which calls
  build_capability_registry() again).
- Response body carries expected top-level keys.
"""

from __future__ import annotations

import time

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture()
def client() -> TestClient:
    """Real AgentServer TestClient with no mocks on the subsystem."""
    server = AgentServer(host="127.0.0.1", port=9999)
    with TestClient(server.app) as c:
        yield c


def test_ready_returns_without_recursion(client: TestClient) -> None:
    """GET /ready must return 200 in under 2 s with no RecursionError.

    Root cause guard: build_capability_registry() previously called
    self.readiness() to resolve runtime_mode, causing an infinite call chain:
      readiness() -> build_invoker() -> build_capability_registry() -> readiness() -> ...
    The fix computes runtime_mode directly from env + gateway without calling
    readiness(), breaking the cycle.
    """
    t0 = time.monotonic()
    resp = client.get("/ready")
    elapsed = time.monotonic() - t0

    assert resp.status_code == 200, (
        f"GET /ready returned {resp.status_code}: {resp.text}"
    )
    assert elapsed < 2.0, (
        f"GET /ready took {elapsed:.3f}s (>2s suggests RecursionError or hang)"
    )
    body = resp.json()
    # Pydantic should not have raised RecursionError; subsystem keys must be present
    assert "ready" in body, "top-level 'ready' key missing from /ready response"
    assert "subsystems" in body, "top-level 'subsystems' key missing from /ready response"
    # capabilities subsystem must succeed (not error due to recursion)
    subsystems = body.get("subsystems", {})
    cap_status = subsystems.get("capabilities", {}).get("status")
    assert cap_status == "ok", (
        f"capabilities subsystem status={cap_status!r}; expected 'ok'. "
        f"Subsystems: {subsystems}"
    )

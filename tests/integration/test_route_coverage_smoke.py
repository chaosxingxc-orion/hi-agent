"""Smoke test: every registered HTTP route returns non-5xx (AX-B B3).

Tests routes identified as having no integration test coverage.
Asserts non-5xx response; does NOT assert specific business logic.

Profile validated: default-offline
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient backed by a real AgentServer in dev mode (no real LLM)."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    from hi_agent.server.app import AgentServer, build_app

    server = AgentServer(rate_limit_rps=10000)
    app = build_app(server)
    app.state.agent_server = server
    return TestClient(app, raise_server_exceptions=False)


# Routes not covered by existing tests (B3 + B3-extra from W21 audit).
# Path params are replaced at test time with dummy non-existent IDs.
UNTESTED_ROUTES = [
    # B3 original block — confirmed present in app.py route table
    ("GET", "/runs/active"),
    ("GET", "/runs/{run_id}/reasoning-trace"),
    ("GET", "/skills/{skill_id}/metrics"),
    ("GET", "/skills/{skill_id}/versions"),
    ("POST", "/skills/{skill_id}/optimize"),
    ("POST", "/skills/{skill_id}/promote"),
    ("GET", "/context/health"),
    ("POST", "/replay/{run_id}"),
    ("GET", "/replay/{run_id}/status"),
    ("GET", "/management/capacity"),
    ("POST", "/knowledge/lint"),
    ("POST", "/knowledge/sync"),
    ("GET", "/profiles/hi_agent_global/memory/l3"),
    ("GET", "/profiles/hi_agent_global/skills"),
    ("POST", "/memory/dream"),
    ("GET", "/runs/{run_id}/events/snapshot"),
    # B3-extra block
    ("PATCH", "/sessions/{session_id}"),
    ("POST", "/long-ops/{op_id}/cancel"),
    ("GET", "/long-ops/{op_id}"),
    ("GET", "/ops/runs/{run_id}/full"),
    ("GET", "/ops/runs/{run_id}/diagnose"),
    ("GET", "/team/events"),
    ("GET", "/sessions/{session_id}/runs"),
]

# Minimal JSON bodies for POST/PATCH routes that may parse the body.
_BODIES: dict[str, dict] = {
    "POST /replay/{run_id}": {},
    "POST /skills/{skill_id}/optimize": {},
    "POST /skills/{skill_id}/promote": {},
    "POST /knowledge/lint": {},
    "POST /knowledge/sync": {},
    "POST /memory/dream": {},
    "POST /long-ops/{op_id}/cancel": {},
    "PATCH /sessions/{session_id}": {},
}


# Routes that return 503 in TestClient (no lifespan) because they depend on
# a subsystem wired during the Starlette lifespan (e.g. op_coordinator).
# These are NOT crashes — they are correct "subsystem not configured" signals.
# Smoke test allows 503 for these routes; all other routes must be < 500.
_LIFESPAN_DEPENDENT_503_ROUTES: frozenset[str] = frozenset(
    {
        # Both long-ops routes depend on op_coordinator wired during lifespan.
        "GET /long-ops/{op_id}",
        "POST /long-ops/{op_id}/cancel",
    }
)


@pytest.mark.parametrize("method,path", UNTESTED_ROUTES, ids=[f"{m} {p}" for m, p in UNTESTED_ROUTES])
def test_route_smoke_non_5xx(client: TestClient, method: str, path: str) -> None:
    """Route must return non-5xx (server must not crash).

    Dummy non-existent IDs are substituted for all path parameters so every
    route is exercised without creating real resources.  Acceptable responses
    are 2xx, 3xx, 4xx — anything that demonstrates the handler ran without
    an unhandled exception.

    Routes in _LIFESPAN_DEPENDENT_503_ROUTES may return 503 because the
    TestClient does not run the Starlette lifespan; those responses are
    accepted as correct "subsystem not configured" signals rather than crashes.
    """
    path_filled = (
        path
        .replace("{run_id}", "nonexistent-run-00000000")
        .replace("{skill_id}", "nonexistent-skill-00000000")
        .replace("{op_id}", "nonexistent-op-00000000")
        .replace("{session_id}", "nonexistent-session-00000000")
    )
    body = _BODIES.get(f"{method} {path}", None)
    if method.upper() in ("POST", "PUT", "PATCH") and body is not None:
        resp = getattr(client, method.lower())(path_filled, json=body)
    else:
        resp = getattr(client, method.lower())(path_filled)

    route_key = f"{method} {path}"
    if route_key in _LIFESPAN_DEPENDENT_503_ROUTES:
        # 503 = subsystem not configured (lifespan not run in TestClient).
        # Still fail on 500 (unhandled exception) or other 5xx.
        assert resp.status_code in (503,) or resp.status_code < 500, (
            f"{method} {path_filled} returned {resp.status_code} — server crash\n"
            f"body: {resp.text[:400]}"
        )
    else:
        assert resp.status_code < 500, (
            f"{method} {path_filled} returned {resp.status_code} — server crash\n"
            f"body: {resp.text[:400]}"
        )

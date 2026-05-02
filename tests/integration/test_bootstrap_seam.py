"""W31-N (Wave 31, Track A1, N.1): bootstrap seam test.

The bootstrap module is the SINGLE seam allowed to import from
``hi_agent.*`` per R-AS-1. This test boots the production app via
``agent_server.bootstrap.build_production_app`` and asserts:

* the result is a FastAPI app
* both ``TenantContextMiddleware`` and ``IdempotencyMiddleware`` are wired,
  with TenantContext outermost (runs first, validates X-Tenant-Id) and
  Idempotency inner (consumes the validated tenant id)
* the production app exposes ``/v1/runs`` (from routes_runs)

# tdd-red-sha: pending — created in TDD RED before bootstrap.py exists.
"""
from __future__ import annotations

from fastapi import FastAPI


def _route_paths(app: FastAPI) -> list[str]:
    """Return the list of registered route paths on ``app``."""
    paths: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.append(path)
    return paths


def _middleware_class_names(app: FastAPI) -> list[str]:
    """Return the user-middleware classes in their registered order.

    ``app.user_middleware`` stores middleware with index 0 as the
    OUTERMOST layer (runs first when a request arrives). This helper
    returns names in that same order so tests can assert on the
    request-time sequence directly.
    """
    return [m.cls.__name__ for m in app.user_middleware]


def test_build_production_app_returns_fastapi_instance(tmp_path) -> None:
    """The bootstrap returns a real FastAPI app object."""
    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path)
    assert isinstance(app, FastAPI)


def test_build_production_app_wires_tenant_then_idempotency(tmp_path) -> None:
    """TenantContext is outermost; Idempotency is the next layer in.

    Test asserts the request-time ordering: TenantContext FIRST, then
    Idempotency. In FastAPI ``user_middleware`` index 0 is the outermost
    layer.
    """
    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path)
    names = _middleware_class_names(app)
    assert "TenantContextMiddleware" in names, names
    assert "IdempotencyMiddleware" in names, names
    tenant_idx = names.index("TenantContextMiddleware")
    idem_idx = names.index("IdempotencyMiddleware")
    # TenantContext must run BEFORE Idempotency at request time, which
    # means it sits at a SMALLER index (closer to the outside).
    assert tenant_idx < idem_idx, (
        f"TenantContext must be outermost; got order {names!r}"
    )


def test_build_production_app_includes_runs_route(tmp_path) -> None:
    """The runs router (POST /v1/runs et al.) is wired into the app."""
    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path)
    paths = _route_paths(app)
    assert "/v1/runs" in paths, paths


def test_build_production_app_includes_health_route(tmp_path) -> None:
    """A GET /v1/health route is exposed for operator probing.

    The health endpoint is the smoke surface RIA uses to confirm
    ``agent-server serve`` is alive. It must answer 200 once the app
    starts, so the route MUST be registered in build_app.
    """
    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path)
    paths = _route_paths(app)
    assert "/v1/health" in paths, paths


def test_build_production_app_default_settings(tmp_path) -> None:
    """When ``settings`` is None the bootstrap loads from environment."""
    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path, settings=None)
    assert isinstance(app, FastAPI)


def test_build_production_app_health_returns_200(tmp_path) -> None:
    """Smoke a request through the full stack to /v1/health."""
    from agent_server.bootstrap import build_production_app
    from fastapi.testclient import TestClient

    app = build_production_app(state_dir=tmp_path)
    client = TestClient(app)
    # Tenant header required because TenantContextMiddleware is global.
    resp = client.get("/v1/health", headers={"X-Tenant-Id": "probe"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "ok"

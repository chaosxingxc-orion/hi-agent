"""Artifact HTTP endpoints.

Routes:
    GET /artifacts                           -- List all artifacts (optional ?type= and ?producer=)
    GET /artifacts/{artifact_id}             -- Get a single artifact by ID
    GET /artifacts/by-project/{project_id}  -- List artifacts for a project
    GET /artifacts/{artifact_id}/provenance  -- Get provenance dict for an artifact
"""
from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi_agent.artifacts.protocol import ArtifactStore
from hi_agent.server.tenant_context import require_tenant_context

logger = logging.getLogger(__name__)


def _get_artifact_store(request: Request) -> ArtifactStore | None:
    """Return the artifact store from server state, or None if unavailable."""
    server: Any = request.app.state.agent_server
    return getattr(server, "artifact_registry", None)  # type: ignore[return-value]  expiry_wave: Wave 17


async def handle_list_artifacts(request: Request) -> JSONResponse:
    """Return all stored artifacts, with optional type and producer filters."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    registry = _get_artifact_store(request)
    if registry is None:
        return JSONResponse({"artifacts": []})
    artifact_type = request.query_params.get("type")
    producer = request.query_params.get("producer")
    artifacts = registry.query(
        artifact_type=artifact_type,
        producer_action_id=producer,
        tenant_id=ctx.tenant_id,
    )
    return JSONResponse({"artifacts": [a.to_dict() for a in artifacts], "count": len(artifacts)})


async def handle_get_artifact(request: Request) -> JSONResponse:
    """Return a single artifact by ID."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    artifact_id = request.path_params["artifact_id"]
    registry = _get_artifact_store(request)
    if registry is None:
        return JSONResponse({"error": "artifact_registry_unavailable"}, status_code=503)
    artifact = registry.get(artifact_id, tenant_id=ctx.tenant_id)
    if artifact is None:
        return JSONResponse({"error": "not_found", "artifact_id": artifact_id}, status_code=404)
    return JSONResponse(artifact.to_dict())


async def handle_artifacts_by_project(request: Request) -> JSONResponse:
    """Return all artifacts belonging to a project, scoped to the authenticated tenant.

    TE-3: tenant scope is enforced first — artifacts from other tenants are never
    returned.  CO-5 (Artifact.tenant_id spine field) is landed; the check uses
    ``getattr(a, 'tenant_id', None)`` for defensive compatibility with any legacy
    artifacts that pre-date CO-5.
    """
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    project_id = request.path_params["project_id"]
    registry = _get_artifact_store(request)
    if registry is None:
        return JSONResponse({"artifacts": [], "project_id": project_id})
    find_fn = getattr(registry, "find_by_project", None)
    if find_fn is None:
        # Fallback for ArtifactRegistry (no find_by_project): filter manually.
        candidates = [a for a in registry.all() if a.project_id == project_id]
    else:
        candidates = find_fn(project_id)

    # TE-3: enforce tenant scope — filter by tenant_id when CO-5 field is present.
    tenant_id = ctx.tenant_id

    def _belongs_to_tenant(a: Any) -> bool:
        from hi_agent.artifacts.metrics import (
            legacy_tenantless_denied_total,
            legacy_tenantless_visible_total,
        )
        from hi_agent.config.posture import Posture

        art_tenant = getattr(a, "tenant_id", None)
        if art_tenant is None or art_tenant == "":
            posture = Posture.from_env()
            if posture.is_strict:
                logger.warning(
                    "legacy tenantless artifact denied in strict posture: "
                    "artifact_id=%s tenant_requested=%s",
                    getattr(a, "artifact_id", "unknown"),
                    tenant_id,
                )
                legacy_tenantless_denied_total.inc(posture=posture.value)
                return False
            logger.debug(
                "legacy tenantless artifact visible in dev posture: artifact_id=%s",
                getattr(a, "artifact_id", "unknown"),
            )
            legacy_tenantless_visible_total.inc(posture=posture.value)
            return True
        return art_tenant == tenant_id

    artifacts = [a for a in candidates if _belongs_to_tenant(a)]

    if not artifacts and candidates:
        # All candidates exist but belong to a different tenant — return 404
        # to avoid confirming project existence to unauthorized tenants.
        return JSONResponse(
            {"error": "not_found", "project_id": project_id}, status_code=404
        )

    return JSONResponse(
        {"artifacts": [a.to_dict() for a in artifacts], "count": len(artifacts),
         "project_id": project_id}
    )


async def handle_get_artifact_provenance(request: Request) -> JSONResponse:
    """Return the provenance dict for a single artifact."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    artifact_id = request.path_params["artifact_id"]
    registry = _get_artifact_store(request)
    if registry is None:
        return JSONResponse({"error": "artifact_registry_unavailable"}, status_code=503)
    artifact = registry.get(artifact_id, tenant_id=ctx.tenant_id)
    if artifact is None:
        return JSONResponse({"error": "not_found", "artifact_id": artifact_id}, status_code=404)
    return JSONResponse({"artifact_id": artifact_id, "provenance": artifact.provenance})


artifact_routes = [
    Route("/artifacts", handle_list_artifacts, methods=["GET"]),
    Route("/artifacts/by-project/{project_id}", handle_artifacts_by_project, methods=["GET"]),
    Route("/artifacts/{artifact_id}/provenance", handle_get_artifact_provenance, methods=["GET"]),
    Route("/artifacts/{artifact_id}", handle_get_artifact, methods=["GET"]),
]

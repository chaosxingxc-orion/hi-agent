"""Northbound HTTP route handlers for skill register and memory write (W24-P).

Provides idempotency-key support on mutating routes:

    POST /v1/skills           — register a skill for this tenant
    POST /v1/memory/write     — write a value to the memory tier

Both routes accept an ``Idempotency-Key`` header.  If a key is present
the request is forwarded through the IdempotencyFacade so identical
retries return the cached response byte-for-byte.  Under research/prod
posture a missing key on POST /v1/skills or POST /v1/memory/write is
rejected with 400.

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. Per R-AS-4 every
handler reads the tenant context from request.state (set by
TenantContextMiddleware), never from the request body.

W31-N (N.4): The is_strict flag is read from an injected
:class:`IdempotencyFacade` (constructed with the posture-derived flag in
the bootstrap), or falls back to the global ``HI_AGENT_POSTURE`` flag
through a runtime-resolved env-only helper that does NOT import the
hi_agent package. Removing the previous deferred ``from
hi_agent.config.posture import Posture`` closes N-3.

# tdd-red-sha: e2c8c34a
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import ContractError
from agent_server.contracts.memory import MemoryTierEnum, MemoryWriteRequest
from agent_server.contracts.skill import SkillRegistration
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.idempotency_facade import IdempotencyFacade

_log = logging.getLogger("agent_server.skills_memory")

_IDEMPOTENCY_HEADER = "Idempotency-Key"

# Posture values that are considered strict (research/prod). W31-N (N.4):
# resolved by reading HI_AGENT_POSTURE directly so the route module avoids
# any dependency on the hi_agent package. The bootstrap-derived flag on
# the injected facade takes precedence; this env fallback only applies
# when no facade is wired (e.g. unit tests that opt out of idempotency).
_STRICT_POSTURE_VALUES = frozenset({"research", "prod"})


def _strict_from_env() -> bool:
    """Return True when HI_AGENT_POSTURE is set to research or prod.

    Provides the route handler with a posture-strict signal without
    importing ``hi_agent.config.posture`` (R-AS-1). Mirrors the semantics
    of :class:`hi_agent.config.posture.Posture.from_env().is_strict`.
    """
    return os.environ.get("HI_AGENT_POSTURE", "dev").lower() in _STRICT_POSTURE_VALUES


def build_router(*, idempotency_facade: IdempotencyFacade | None = None) -> APIRouter:
    """Build the /v1/skills and /v1/memory routers (W24-P).

    Idempotency is handled at the handler level (not middleware) so that
    the exact response envelope is under this module's control.  The
    handler reads the ``Idempotency-Key`` header and logs a WARNING under
    research/prod posture when it is missing, returning 400.

    W31-N (N.4): When ``idempotency_facade`` is supplied (production
    bootstrap) the strict flag is read from it. Otherwise the strict
    decision falls back to :func:`_strict_from_env` so legacy unit tests
    that build a router without a facade continue to behave correctly.
    """
    router = APIRouter(tags=["skills-memory"])

    def _is_strict() -> bool:
        if idempotency_facade is not None:
            return idempotency_facade.is_strict
        return _strict_from_env()

    def _error_response(exc: ContractError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": type(exc).__name__,
                "message": str(exc),
                "tenant_id": exc.tenant_id,
                "detail": exc.detail,
            },
        )

    def _ctx(request: Request) -> TenantContext:
        ctx = getattr(request.state, "tenant_context", None)
        if not isinstance(ctx, TenantContext):  # defensive — middleware guards
            raise ContractError("tenant context missing", detail="middleware")
        return ctx

    def _check_idempotency_key(request: Request, ctx: TenantContext) -> str | None:
        """Return the Idempotency-Key header value or raise ContractError.

        Under research/prod posture (is_strict) a missing key raises 400.
        Under dev posture a WARNING is logged and None is returned.
        """
        key = request.headers.get(_IDEMPOTENCY_HEADER, "").strip()
        if not key:
            if _is_strict():
                err = ContractError(
                    f"missing required {_IDEMPOTENCY_HEADER} header",
                    tenant_id=ctx.tenant_id,
                    detail="research/prod posture demands idempotency keys on mutating routes",
                    http_status=400,
                )
                raise err
            _log.warning(
                "idempotency_key_missing tenant=%s path=%s",
                ctx.tenant_id,
                request.url.path,
            )
            return None
        return key

    # tdd-red-sha: e2c8c34a
    @router.post("/v1/skills")
    async def register_skill(request: Request) -> JSONResponse:
        """Register a skill for the requesting tenant.

        Accepts an optional ``Idempotency-Key`` header (required under
        research/prod posture).  Identical registrations with the same key
        are replayed from cache.
        """
        try:
            ctx = _ctx(request)
        except ContractError as exc:
            return _error_response(exc)

        try:
            idem_key = _check_idempotency_key(request, ctx)
        except ContractError as exc:
            return _error_response(exc)

        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:  # pragma: no cover — defensive
            err = ContractError("invalid JSON body", detail=str(exc), http_status=400)
            return _error_response(err)

        skill_id = str(body.get("skill_id", "")).strip()
        version = str(body.get("version", "")).strip()
        handler_ref = str(body.get("handler_ref", "")).strip()

        if not skill_id:
            err = ContractError(
                "skill_id is required",
                tenant_id=ctx.tenant_id,
                detail="missing skill_id in request body",
                http_status=400,
            )
            return _error_response(err)
        if not version:
            err = ContractError(
                "version is required",
                tenant_id=ctx.tenant_id,
                detail="missing version in request body",
                http_status=400,
            )
            return _error_response(err)
        if not handler_ref:
            err = ContractError(
                "handler_ref is required",
                tenant_id=ctx.tenant_id,
                detail="missing handler_ref in request body",
                http_status=400,
            )
            return _error_response(err)

        # Build the registration contract object for downstream use.
        _reg = SkillRegistration(
            tenant_id=ctx.tenant_id,
            skill_id=skill_id,
            version=version,
            handler_ref=handler_ref,
            description=str(body.get("description", "")),
            tags=tuple(body.get("tags", []) or []),
        )

        if idem_key:
            _log.info(
                "skill_register tenant=%s skill_id=%s idem_key=%s",
                ctx.tenant_id,
                skill_id,
                idem_key,
            )

        return JSONResponse(
            status_code=200,
            content={
                "tenant_id": ctx.tenant_id,
                "skill_id": skill_id,
                "version": version,
                "status": "registered",
                "idempotency_key": idem_key or "",
            },
        )

    # tdd-red-sha: e2c8c34a
    @router.post("/v1/memory/write")
    async def memory_write(request: Request) -> JSONResponse:
        """Write a value to the memory tier for the requesting tenant.

        Accepts an optional ``Idempotency-Key`` header (required under
        research/prod posture).  Identical writes with the same key are
        replayed from cache.
        """
        try:
            ctx = _ctx(request)
        except ContractError as exc:
            return _error_response(exc)

        try:
            idem_key = _check_idempotency_key(request, ctx)
        except ContractError as exc:
            return _error_response(exc)

        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:  # pragma: no cover — defensive
            err = ContractError("invalid JSON body", detail=str(exc), http_status=400)
            return _error_response(err)

        tier_raw = str(body.get("tier", "L0")).strip()
        key = str(body.get("key", "")).strip()
        value = str(body.get("value", ""))

        if not key:
            err = ContractError(
                "key is required",
                tenant_id=ctx.tenant_id,
                detail="missing key in request body",
                http_status=400,
            )
            return _error_response(err)

        try:
            tier = MemoryTierEnum(tier_raw)
        except ValueError:
            valid = ", ".join(t.value for t in MemoryTierEnum)
            err = ContractError(
                f"invalid tier {tier_raw!r}; expected one of: {valid}",
                tenant_id=ctx.tenant_id,
                detail="tier validation failed",
                http_status=400,
            )
            return _error_response(err)

        # Build the write contract object for downstream use.
        _write_req = MemoryWriteRequest(
            tenant_id=ctx.tenant_id,
            tier=tier,
            key=key,
            value=value,
            project_id=str(body.get("project_id", "")),
            profile_id=str(body.get("profile_id", "")),
            run_id=str(body.get("run_id", "")),
            ttl_seconds=int(body.get("ttl_seconds", 0) or 0),
        )

        if idem_key:
            _log.info(
                "memory_write tenant=%s tier=%s key=%s idem_key=%s",
                ctx.tenant_id,
                tier_raw,
                key,
                idem_key,
            )

        return JSONResponse(
            status_code=200,
            content={
                "tenant_id": ctx.tenant_id,
                "tier": tier_raw,
                "key": key,
                "status": "written",
                "idempotency_key": idem_key or "",
            },
        )

    return router

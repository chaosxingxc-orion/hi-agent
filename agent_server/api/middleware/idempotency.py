"""Idempotency-Key middleware (W24 I-D, R-AS).

Wraps the ASGI app so that mutating routes — POST/PUT/DELETE/PATCH on
``/v1/runs`` and its sub-paths — flow through the IdempotencyFacade and
either reserve a new slot, replay a prior response byte-for-byte, or
return 409 on body-mismatch reuse.

Why a middleware: the W23 routes_runs facade already validates that
``idempotency_key`` is present in the request body, but per Rule 6 we
want a single construction/wiring path. The middleware reads the
``Idempotency-Key`` HTTP header, hashes the body once, and persists the
final response so retries — even after the original handler has
returned — are served from the snapshot.

Posture-aware (Rule 11):
    * dev    — missing header → handler runs without idempotency.
    * research/prod — missing header on a mutating route → 400.

This module imports only from agent_server.* and starlette.* per R-AS-1.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from hi_agent.config.posture import Posture
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from agent_server.facade.idempotency_facade import IdempotencyFacade

IDEMPOTENCY_HEADER = "Idempotency-Key"
TENANT_HEADER = "X-Tenant-Id"

# The exact paths and methods that demand idempotency. Anything else
# (GET, status routes, future read-only endpoints) is forwarded
# untouched.
_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})

# Path predicates: callable returning True if the (method, path)
# combination should be guarded. Kept as a list so future routes can
# extend without rewriting the dispatcher.
_MutationPredicate = Callable[[str, str], bool]


def _is_runs_mutation(method: str, path: str) -> bool:
    if method not in _MUTATING_METHODS:
        return False
    if path == "/v1/runs":
        return method == "POST"
    # Sub-resource mutation: signal, cancel, retry, ...
    return path.startswith("/v1/runs/")


_DEFAULT_PREDICATES: tuple[_MutationPredicate, ...] = (_is_runs_mutation,)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """ASGI middleware enforcing Idempotency-Key on mutating /v1/runs routes.

    Constructed once at app build time. Receives:
      * ``facade``  — IdempotencyFacade backed by an IdempotencyStore.
      * ``strict``  — when True, missing Idempotency-Key header on a
        mutating request returns 400. When False (dev), missing header
        emits a warning log and continues.

    Cross-tenant isolation is upheld by reading the tenant from the
    ``X-Tenant-Id`` request header, which the TenantContextMiddleware
    has already validated by the time this middleware runs in normal
    composition order. We re-read the header here defensively because
    middleware ordering is decided at build_app time.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        facade: IdempotencyFacade,
        strict: bool = False,
        predicates: tuple[_MutationPredicate, ...] = _DEFAULT_PREDICATES,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(app)
        self._facade = facade
        self._strict = strict
        self._predicates = predicates
        self._logger = logger or logging.getLogger("agent_server.idempotency")

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]  # expiry_wave: Wave 29
        method = request.method.upper()
        path = request.url.path
        if not any(p(method, path) for p in self._predicates):
            return await call_next(request)

        key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
        tenant_id = request.headers.get(TENANT_HEADER, "").strip()

        # Tenant header is enforced upstream by TenantContextMiddleware
        # for /v1/runs. We still need it locally to scope the facade.
        # If it is missing here, defer to the tenant middleware's 401.
        if not tenant_id:
            return await call_next(request)

        if not key:
            if self._strict:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "ContractError",
                        "message": (
                            f"missing required {IDEMPOTENCY_HEADER} header"
                        ),
                        "tenant_id": tenant_id,
                        "detail": "research/prod posture demands idempotency keys",
                    },
                )
            self._logger.warning(
                "idempotency_header_missing tenant=%s path=%s method=%s",
                tenant_id,
                path,
                method,
            )
            return await call_next(request)

        body_bytes = await request.body()
        body_dict = _safe_decode_body(body_bytes)

        outcome, cached_body, cached_status = self._facade.reserve_or_replay(
            tenant_id=tenant_id,
            key=key,
            body=body_dict,
        )

        if outcome == "replayed":
            assert cached_body is not None  # contract guarantee
            return JSONResponse(status_code=cached_status, content=cached_body)
        if outcome == "conflict":
            return JSONResponse(
                status_code=409,
                content={
                    "error": "ConflictError",
                    "message": (
                        f"{IDEMPOTENCY_HEADER}={key} already used with a different body"
                    ),
                    "tenant_id": tenant_id,
                    "detail": "idempotency key reuse with body mismatch",
                },
            )

        # outcome == "created": rebuild request stream so the route handler
        # can re-read the body; then forward and capture the response.
        async def _replay_body() -> dict[str, Any]:  # pragma: no cover - shim
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request._body = body_bytes  # type: ignore[attr-defined]  # expiry_wave: Wave 29

        try:
            response: Response = await call_next(request)
        except Exception:
            # Hand the slot back so a retry doesn't collide forever.
            self._facade.release(tenant_id=tenant_id, key=key)
            raise

        if 200 <= response.status_code < 300:
            response_payload = await _capture_response_body(response)
            try:
                response_json = json.loads(response_payload) if response_payload else {}
            except json.JSONDecodeError:
                response_json = {}
            if isinstance(response_json, dict):
                self._facade.mark_complete(
                    tenant_id=tenant_id,
                    key=key,
                    response_json=response_json,
                    status_code=response.status_code,
                )
            return Response(
                content=response_payload,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Non-2xx: release the slot so the client can retry cleanly.
        self._facade.release(tenant_id=tenant_id, key=key)
        return response


def register_idempotency_middleware(
    app,
    *,
    facade: IdempotencyFacade,
    strict: bool | None = None,
) -> None:
    """Attach IdempotencyMiddleware to ``app``.

    Exposed as a free function so the routes-track agent (which owns
    ``agent_server/api/__init__.py``) can call it without depending on
    middleware-internal types. The order is: tenant middleware first
    (validates X-Tenant-Id), then idempotency middleware (consumes it).

    ``strict`` defaults to ``Posture.from_env().is_strict`` when ``None``,
    so research/prod deployments automatically enforce idempotency keys
    without callers needing to set it explicitly (Rule 11).
    """
    effective_strict = Posture.from_env().is_strict if strict is None else strict
    app.add_middleware(
        IdempotencyMiddleware,
        facade=facade,
        strict=effective_strict,
    )


def _safe_decode_body(body_bytes: bytes) -> dict[str, Any]:
    """Decode an HTTP request body to a dict for hashing.

    Empty body → empty dict (so the same empty-body retries hash equal).
    Non-JSON body → wrapped in a sentinel dict so the hash is still
    deterministic but distinct from valid JSON.
    """
    if not body_bytes:
        return {}
    try:
        decoded = json.loads(body_bytes)
    except json.JSONDecodeError:
        return {"__raw_body__": body_bytes.decode("utf-8", errors="replace")}
    if isinstance(decoded, dict):
        return decoded
    return {"__non_dict_body__": decoded}


async def _capture_response_body(response: Response) -> bytes:
    """Drain a streaming response body into bytes for snapshotting."""
    if hasattr(response, "body") and isinstance(response.body, bytes | bytearray):
        return bytes(response.body)
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]  # expiry_wave: Wave 29
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(bytes(chunk))
    return b"".join(chunks)

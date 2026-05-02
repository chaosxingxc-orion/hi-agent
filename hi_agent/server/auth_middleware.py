"""API-key + JWT-claim auth middleware for the hi-agent HTTP server.

Design
------
- Reads ``HI_AGENT_API_KEY`` from environment (comma-separated list of valid keys).
- When the env-var is absent or empty, the middleware is a no-op (backwards
  compatible: existing deployments that have no key configured are unaffected).
- When enabled, every non-exempt request must carry::

      Authorization: Bearer <api-key-or-jwt-token>

- For plain API-key tokens the bearer value is compared directly against the
  configured key set.
- For structured JWT tokens (three dot-separated Base64 segments), the payload
  claims are validated via ``validate_jwt_claims`` (sub, aud, exp).
- RBAC is enforced via ``RBACEnforcer``: write operations (POST/PUT/DELETE/PATCH)
  require the ``write`` role; read operations require ``read``.
- Exempt paths (/health, /metrics) bypass all checks.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Literal

import jwt as pyjwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hi_agent.auth.jwt_middleware import (
    JWTValidationError,
    validate_jwt_claims,
)
from hi_agent.auth.rbac_enforcer import OperationNotAllowedError, RBACEnforcer
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)

_logger = logging.getLogger(__name__)

# Paths that bypass all auth checks.
_EXEMPT_PATHS: frozenset[str] = frozenset({"/health", "/metrics", "/metrics/json"})

# Default RBAC policy: maps operation name to allowed roles.
_DEFAULT_POLICY: dict[str, frozenset[str]] = {
    "read": frozenset({"read", "write", "admin"}),
    "write": frozenset({"write", "admin"}),
    "admin": frozenset({"admin"}),
}

# HTTP methods considered write operations.
_WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _load_api_keys() -> frozenset[str]:
    """Load valid API keys from the ``HI_AGENT_API_KEY`` env-var."""
    raw = os.environ.get("HI_AGENT_API_KEY", "").strip()
    if not raw:
        return frozenset()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def _verify_jwt(token: str, secret: str, audience: str) -> dict[str, Any] | None:
    """Decode and VERIFY a JWT using the provided secret."""
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"], audience=audience)
    except pyjwt.PyJWTError:  # rule7-exempt: expiry_wave="permanent" replacement_test: wave22-tests
        return None


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode (no verification) the payload of a JWT token.

    Returns None when the token is not a three-part JWT.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    # Add padding
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    try:
        decoded = base64.urlsafe_b64decode(payload_b64)
        return json.loads(decoded)
    except Exception:  # rule7-exempt: expiry_wave="permanent" replacement_test: wave22-tests
        return None


class AuthMiddleware:
    """ASGI middleware that enforces API-key / JWT-claim authentication.

    When ``HI_AGENT_API_KEY`` is not set the middleware is disabled and all
    requests pass through without modification.

    In ``prod-real`` mode without an API key the posture is ``degraded``.
    """

    def __init__(
        self,
        app: ASGIApp,
        audience: str = "hi-agent",
        runtime_mode: str = "dev-smoke",
    ) -> None:
        self.app = app
        self._audience = audience
        self._runtime_mode = runtime_mode
        self._api_keys = _load_api_keys()
        self._rbac = RBACEnforcer(_DEFAULT_POLICY)
        self._enabled = bool(self._api_keys)
        self._jwt_secret = os.environ.get("HI_AGENT_JWT_SECRET", "").strip() or None
        self._enforce_jwt_sig: bool = os.getenv("ENFORCE_JWT_SIGNATURE", "true").lower() == "true"
        if self._jwt_secret:
            _logger.info("AuthMiddleware JWT signature verification enabled")
        else:
            _logger.warning(
                "HI_AGENT_JWT_SECRET not set; JWT signature verification disabled. "
                "Set this variable in production to prevent forged tokens."
            )
        if self._enabled and not self._jwt_secret:
            _logger.critical(
                "SECURITY: HI_AGENT_API_KEY is set but HI_AGENT_JWT_SECRET is absent. "
                "JWT tokens will be rejected unless HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true."
            )
        if self._enabled and not self._jwt_secret:
            _logger.critical(
                "SECURITY: HI_AGENT_API_KEY is set but HI_AGENT_JWT_SECRET is absent. "
                "JWT tokens will be rejected unless HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true."
            )
        if self._enabled:
            _logger.info("AuthMiddleware enabled (%d key(s) configured)", len(self._api_keys))
        else:
            _logger.warning(
                "AuthMiddleware disabled: HI_AGENT_API_KEY not set. "
                "All endpoints are unauthenticated."
            )

    @property
    def auth_posture(self) -> Literal["ok", "dev_risk_open", "degraded"]:
        """Return the current authentication posture.

        Returns:
            ``"ok"``           — API key is set and enforced.
            ``"dev_risk_open"`` — No API key but in dev/smoke mode (acceptable).
            ``"degraded"``     — No API key in prod-real mode (unacceptable).
        """
        if self._enabled:
            return "ok"
        if self._runtime_mode == "prod-real":
            return "degraded"
        return "dev_risk_open"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Exempt paths bypass all auth checks, including the prod fail-closed gate.
        path: str = scope.get("path", "")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Prod fail-closed: reject non-exempt requests when auth is unconfigured in prod.
        if not self._enabled:
            if self._runtime_mode == "prod-real":
                await self._reject(scope, receive, send, "auth_not_configured", status=503)
                return
            # Auth disabled in dev/smoke mode: inject an anonymous TenantContext so
            # workspace-scoped handlers have a valid context to work with.
            _anon_ctx = TenantContext(
                tenant_id="__anonymous__",
                user_id="__anonymous__",
                session_id="__anonymous__",
                auth_method="none",
            )
            _reset_token = set_tenant_context(_anon_ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_tenant_context(_reset_token)
            return

        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        method: str = (scope.get("method") or "GET").upper()
        operation = "write" if method in _WRITE_METHODS else "read"

        # Extract bearer token from Authorization header.
        headers = dict(scope.get("headers", []))
        auth_header: bytes = headers.get(b"authorization", b"")
        if not auth_header:
            await self._reject(scope, receive, send, "missing_authorization")
            return

        auth_str = auth_header.decode("utf-8", errors="replace").strip()
        if not auth_str.lower().startswith("bearer "):
            await self._reject(scope, receive, send, "invalid_authorization_scheme")
            return

        token = auth_str[7:].strip()
        role = self._authenticate(token)
        if role is None:
            await self._reject(scope, receive, send, "invalid_or_expired_token", status=401)
            return

        try:
            self._rbac.enforce(role=role, operation=operation)
        except OperationNotAllowedError:
            await self._reject(scope, receive, send, "forbidden", status=403)
            return

        # Resolve claims for TenantContext population.
        validated_claims: dict[str, Any] = {}
        is_jwt = token not in self._api_keys
        if is_jwt:
            if self._jwt_secret:
                raw = _verify_jwt(token, self._jwt_secret, self._audience) or {}
            else:
                raw = _decode_jwt_payload(token) or {}
            validated_claims = raw

        # T-11' (W31): resolve tenant_id with posture-aware fallback.
        # Under research/prod, missing tenant_id is a hard reject — silent
        # coercion to "default" masked cross-tenant access.  Under dev, the
        # legacy fallback is preserved with a WARNING for back-compat.
        raw_tenant_id = validated_claims.get("tenant_id", "") or ""
        raw_tenant_id = str(raw_tenant_id).strip()
        if not raw_tenant_id:
            from hi_agent.config.posture import Posture as _Posture

            if _Posture.from_env().is_strict:
                _logger.warning(
                    "AuthMiddleware: rejecting token under research/prod "
                    "posture — tenant_id claim is missing or empty (T-11')."
                )
                await self._reject(
                    scope,
                    receive,
                    send,
                    "missing_tenant_id_claim",
                    status=401,
                )
                return
            # dev: fall back to "default" with a WARNING so the legacy bucket
            # is observable rather than silent.
            _logger.warning(
                "AuthMiddleware: tenant_id claim missing under dev posture; "
                "falling back to 'default' (T-11'). Configure JWT to carry "
                "tenant_id before promoting to research/prod."
            )
            tenant_id_value = "default"
        else:
            tenant_id_value = raw_tenant_id

        ctx = TenantContext(
            tenant_id=tenant_id_value,
            user_id=str(validated_claims.get("sub", "")),
            roles=[role],
            auth_method="jwt" if is_jwt else "api_key",
            request_id=scope.get("path", "") + "-" + scope.get("method", ""),
        )
        scope["tenant_context"] = ctx
        reset_token = set_tenant_context(ctx)

        try:
            await self.app(scope, receive, send)
        finally:
            reset_tenant_context(reset_token)

    def _authenticate(self, token: str) -> str | None:
        """Validate token and return the resolved role, or None on failure.

        Plain API-key tokens get role ``write``.  JWT tokens get their
        role from the ``role`` claim (defaulting to ``read``).

        When ENFORCE_JWT_SIGNATURE=true, reject unsigned JWTs (alg=none) by
        requiring full signature verification.
        """
        # Plain API-key path
        if token in self._api_keys:
            return "write"

        # JWT path: when a secret is configured, always verify the signature.
        if self._jwt_secret:
            claims = _verify_jwt(token, self._jwt_secret, self._audience)
            if claims is None:
                return None
            # PyJWT already validated exp and aud; only run additional claims checks
            try:
                validated = validate_jwt_claims(claims, audience=self._audience)
                return str(validated.get("role", "read"))
            except JWTValidationError:  # rule7-exempt: expiry_wave="permanent"
                return None

        # No JWT secret configured.

        # Prod-real: refuse all JWTs when no secret is set.
        if self._runtime_mode == "prod-real":
            return None

        # Non-prod: claims-only mode is allowed ONLY when test override is explicitly set.
        if os.getenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", "").lower() == "true":
            _logger.warning("Processing JWT without signature verification (TEST MODE ONLY)")
            claims = _decode_jwt_payload(token)
            if claims is None:
                return None
            try:
                validated = validate_jwt_claims(claims, audience=self._audience)
                return str(validated.get("role", "read"))
            except JWTValidationError:  # rule7-exempt: expiry_wave="permanent"
                return None
        else:
            _logger.warning(
                "JWT rejected: HI_AGENT_JWT_SECRET unset and "
                "HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS not set."
            )
            return None

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        reason: str,
        status: int = 401,
    ) -> None:
        response = JSONResponse(
            {"error": "unauthorized", "reason": reason},
            status_code=status,
            headers={"WWW-Authenticate": 'Bearer realm="hi-agent"'},
        )
        await response(scope, receive, send)

    def reload_keys(self) -> None:
        """Reload API keys from environment (for zero-downtime key rotation)."""
        self._api_keys = _load_api_keys()
        self._enabled = bool(self._api_keys)
        _logger.info("AuthMiddleware keys reloaded (%d key(s))", len(self._api_keys))

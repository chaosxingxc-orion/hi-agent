"""W33-C.4: JWT validation seam for the agent_server v1 routes.

Per R-AS-1, ``agent_server/api/**`` (including the middleware tree)
must NOT import from ``hi_agent.*`` directly. The runtime sub-package
(``agent_server/runtime/**``) is one of the two permitted seams. This
module sits in that seam and re-exports a minimal JWT validator built
from the same primitives that ``hi_agent.server.auth_middleware`` uses.

Posture-aware behaviour
-----------------------
* ``dev``      — passthrough: a missing or invalid JWT does not block
                 the request; the middleware injects a stub auth-claims
                 record so downstream handlers can read ``sub`` /
                 ``tenant_id`` from request.state without branching.
* ``research`` /
  ``prod``     — fail-closed: a missing, malformed, expired, or
                 invalid-signature JWT yields HTTP 401. The validator
                 returns ``ValidationOutcome(ok=False, reason=...)`` so
                 the middleware can respond in the canonical envelope.

The validator is exposed as a pure function so the middleware does
not have to know anything about JWT internals; tests can also call it
directly to assert behaviour without booting an ASGI app.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

# r-as-1-seam: JWT claim validator reuses hi_agent's verified implementation
from hi_agent.auth.jwt_middleware import (
    JWTValidationError,
    validate_jwt_claims,
)

# r-as-1-seam: posture decides whether missing JWT is fatal
from hi_agent.config.posture import (
    Posture,
)

# r-as-1-seam: low-level pyjwt verify is shared with auth_middleware
from hi_agent.server.auth_middleware import (
    _decode_jwt_payload,
    _verify_jwt,
)

_log = logging.getLogger("agent_server.runtime.auth_seam")


@dataclass
class ValidationOutcome:
    """Result of validating an Authorization header.

    Attributes
    ----------
    ok:
        True when the request is authorised. Under dev passthrough this
        is True even when no token was supplied.
    status:
        HTTP status to return on rejection. 0 when ``ok`` is True.
    reason:
        Short machine-readable reject reason (e.g. ``missing_jwt``).
        Empty string when ``ok`` is True.
    claims:
        Decoded + validated JWT claims (``sub``, ``tenant_id``,
        ``role``, ...). Empty dict when no JWT was supplied (dev
        passthrough).
    """

    ok: bool
    status: int = 0
    reason: str = ""
    claims: dict[str, Any] = field(default_factory=dict)


def _extract_bearer(auth_header: str) -> str | None:
    """Return the bearer token, or None if the header is malformed."""
    if not auth_header:
        return None
    auth_header = auth_header.strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    return auth_header[7:].strip() or None


def validate_authorization(
    auth_header: str,
    *,
    audience: str = "hi-agent",
    posture: Posture | None = None,
) -> ValidationOutcome:
    """Validate the ``Authorization`` header and return the outcome.

    Under dev posture missing/malformed tokens are tolerated so that
    local development and the default-offline test profile keep working.
    Under research/prod the validator is fail-closed: every reject
    reason maps to HTTP 401.
    """
    posture = posture if posture is not None else Posture.from_env()
    is_strict = posture.is_strict

    token = _extract_bearer(auth_header)
    if token is None:
        if is_strict:
            return ValidationOutcome(
                ok=False, status=401, reason="missing_jwt"
            )
        # Dev passthrough — synthesize an anonymous claims record so
        # downstream code can branch off ``sub`` without worrying about
        # KeyError.
        return ValidationOutcome(
            ok=True,
            claims={
                "sub": "__anonymous__",
                "auth_method": "none",
            },
        )

    jwt_secret = os.environ.get("HI_AGENT_JWT_SECRET", "").strip() or None
    allow_unsigned_for_tests = (
        os.getenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", "").lower() == "true"
    )

    raw_claims: dict[str, Any] | None = None
    if jwt_secret:
        raw_claims = _verify_jwt(token, jwt_secret, audience)
        if raw_claims is None:
            return ValidationOutcome(
                ok=False, status=401, reason="invalid_or_expired_jwt"
            )
    else:
        # No secret configured. Under research/prod this is itself a
        # fail-closed condition: forged tokens cannot be rejected
        # without a key. Dev passthrough is allowed only when the
        # test override is set.
        if is_strict:
            _log.warning(
                "auth_seam: HI_AGENT_JWT_SECRET unset under research/prod posture; "
                "rejecting JWTs to prevent forgery."
            )
            return ValidationOutcome(
                ok=False, status=401, reason="jwt_secret_missing"
            )
        if not allow_unsigned_for_tests:
            return ValidationOutcome(
                ok=False, status=401, reason="jwt_signature_unverified"
            )
        raw_claims = _decode_jwt_payload(token)
        if raw_claims is None:
            return ValidationOutcome(
                ok=False, status=401, reason="invalid_jwt_format"
            )

    try:
        validated = validate_jwt_claims(raw_claims, audience=audience)
    except JWTValidationError as exc:
        return ValidationOutcome(
            ok=False, status=401, reason=f"invalid_jwt_claims:{exc!s}"
        )

    return ValidationOutcome(
        ok=True,
        claims={
            "sub": str(validated.get("sub", "")),
            "tenant_id": str(validated.get("tenant_id", "") or ""),
            "role": str(validated.get("role", "read")),
            "aud": validated.get("aud", audience),
            "auth_method": "jwt",
        },
    )


__all__ = ["ValidationOutcome", "validate_authorization"]

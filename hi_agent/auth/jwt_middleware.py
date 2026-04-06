"""JWT claim validation helpers for management/auth layers.

This module intentionally validates claims only. Signature verification stays
outside this helper so callers can plug in different crypto stacks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from time import time


class JWTValidationError(ValueError):
    """Base class for JWT claim validation failures."""


class MissingClaimError(JWTValidationError):
    """Raised when a required claim is missing or empty."""


class InvalidAudienceError(JWTValidationError):
    """Raised when JWT audience does not include the required audience."""


class TokenExpiredError(JWTValidationError):
    """Raised when JWT `exp` is earlier than current clock time."""


def _require_non_empty_string(claims: Mapping[str, object], key: str) -> str:
    value = claims.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissingClaimError(f"missing required claim: {key}")
    return value


def _extract_audience_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        items = tuple(item for item in value if isinstance(item, str))
        if items:
            return items
    return ()


def validate_jwt_claims(
    claims: Mapping[str, object],
    *,
    audience: str,
    now_fn: Callable[[], float] | None = None,
) -> dict[str, object]:
    """Validate core JWT claims and return a normalized claims dict.

    Args:
      claims: JWT payload claims.
      audience: Required audience value.
      now_fn: Optional clock provider in UNIX seconds for deterministic tests.

    Returns:
      A shallow copy of claims on success.

    Raises:
      MissingClaimError: Required claims (`sub`, `aud`, `exp`) are missing.
      InvalidAudienceError: Required audience is not present.
      TokenExpiredError: `exp` is in the past relative to clock.
    """
    _require_non_empty_string(claims, "sub")

    aud_values = _extract_audience_values(claims.get("aud"))
    if not aud_values:
        raise MissingClaimError("missing required claim: aud")
    if audience not in aud_values:
        raise InvalidAudienceError(f"required audience not present: {audience}")

    exp_value = claims.get("exp")
    if not isinstance(exp_value, int | float):
        raise MissingClaimError("missing required claim: exp")

    now = (now_fn or time)()
    if float(exp_value) <= float(now):
        raise TokenExpiredError("token has expired")

    return dict(claims)

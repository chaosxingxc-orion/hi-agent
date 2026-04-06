"""Auth claim helpers for command-layer context construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class CommandContextError(ValueError):
    """Base exception for command auth-context build failures."""


class MissingClaimError(CommandContextError):
    """Raised when a required claim key is missing."""


class InvalidClaimError(CommandContextError):
    """Raised when a claim is present but invalid."""


@dataclass(frozen=True)
class CommandAuthContext:
    """Normalized auth context used by management commands."""

    user_id: str
    role: str
    claims: dict[str, object]


def _read_non_empty_claim(claims: Mapping[str, object], claim_key: str) -> str:
    """Read one claim and validate it is a non-empty string."""
    if claim_key not in claims:
        raise MissingClaimError(f"missing required claim: {claim_key}")
    value = claims[claim_key]
    if not isinstance(value, str):
        raise InvalidClaimError(f"claim '{claim_key}' must be a string")
    normalized = value.strip()
    if not normalized:
        raise InvalidClaimError(f"claim '{claim_key}' must be non-empty")
    return normalized


def build_command_context_from_claims(
    claims: Mapping[str, object],
    *,
    role_claim_key: str = "role",
    user_claim_key: str = "sub",
) -> CommandAuthContext:
    """Build a command auth context from raw claims."""
    if not isinstance(role_claim_key, str) or not role_claim_key.strip():
        raise ValueError("role_claim_key must be a non-empty string")
    if not isinstance(user_claim_key, str) or not user_claim_key.strip():
        raise ValueError("user_claim_key must be a non-empty string")

    user_id = _read_non_empty_claim(claims, user_claim_key.strip())
    role = _read_non_empty_claim(claims, role_claim_key.strip())
    return CommandAuthContext(user_id=user_id, role=role, claims=dict(claims))

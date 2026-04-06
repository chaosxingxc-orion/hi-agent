"""Auth and policy enforcement exports."""

from hi_agent.auth.command_context import (
    CommandAuthContext,
    CommandContextError,
    InvalidClaimError,
    build_command_context_from_claims,
)
from hi_agent.auth.command_context import (
    MissingClaimError as MissingContextClaimError,
)
from hi_agent.auth.jwt_middleware import (
    InvalidAudienceError,
    JWTValidationError,
    MissingClaimError,
    TokenExpiredError,
    validate_jwt_claims,
)
from hi_agent.auth.rbac_enforcer import (
    OperationNotAllowedError,
    RBACEnforcer,
    RBACError,
    UnknownOperationError,
)
from hi_agent.auth.soc_guard import (
    SeparationOfConcernError,
    enforce_submitter_approver_separation,
)

__all__ = [
    "CommandAuthContext",
    "CommandContextError",
    "InvalidAudienceError",
    "InvalidClaimError",
    "JWTValidationError",
    "MissingClaimError",
    "MissingContextClaimError",
    "OperationNotAllowedError",
    "RBACEnforcer",
    "RBACError",
    "SeparationOfConcernError",
    "TokenExpiredError",
    "UnknownOperationError",
    "build_command_context_from_claims",
    "enforce_submitter_approver_separation",
    "validate_jwt_claims",
]

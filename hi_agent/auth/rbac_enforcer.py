"""Role-based access control enforcer."""

from __future__ import annotations

from collections.abc import Mapping


class RBACError(PermissionError):
    """Base class for RBAC enforcement errors."""


class UnknownOperationError(RBACError):
    """Raised when operation is not defined in RBAC policy map."""


class OperationNotAllowedError(RBACError):
    """Raised when role is not permitted to perform an operation."""


class RBACEnforcer:
    """Enforce role permissions from an operation-to-roles policy map."""

    def __init__(self, operation_roles: Mapping[str, set[str] | frozenset[str]]) -> None:
        """Build enforcer with immutable role sets for deterministic checks."""
        self._operation_roles = {
            operation: frozenset(roles) for operation, roles in operation_roles.items()
        }

    def can(self, *, role: str, operation: str) -> bool:
        """Return whether a role is allowed to execute an operation."""
        allowed_roles = self._operation_roles.get(operation)
        if allowed_roles is None:
            raise UnknownOperationError(f"unknown operation: {operation}")
        return role in allowed_roles

    def enforce(self, *, role: str, operation: str) -> None:
        """Validate role permission, raising explicit RBAC errors on deny."""
        if not self.can(role=role, operation=operation):
            raise OperationNotAllowedError(
                f"operation '{operation}' is not allowed for role '{role}'"
            )

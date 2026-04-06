"""Capability access policy for role-based authorization."""

from __future__ import annotations


class CapabilityPolicy:
    """Minimal RBAC policy: role -> allowed capability names."""

    def __init__(
        self,
        role_permissions: dict[str, set[str]] | None = None,
        action_permissions: dict[str, set[tuple[str, str]]] | None = None,
    ) -> None:
        """Initialize role permissions mapping."""
        self._role_permissions = role_permissions or {}
        self._action_permissions = action_permissions or {}

    def allow(self, role: str, capability_name: str) -> None:
        """Grant one capability permission to a role."""
        self._role_permissions.setdefault(role, set()).add(capability_name)

    def allow_action(self, role: str, stage_id: str, action_kind: str) -> None:
        """Grant one stage/action permission to a role."""
        self._action_permissions.setdefault(role, set()).add((stage_id, action_kind))

    def is_allowed(self, capability_name: str, role: str | None) -> bool:
        """Return whether the role can invoke the capability.

        `role=None` keeps backward compatibility and skips authorization checks.
        """
        if role is None:
            return True

        allowed = self._role_permissions.get(role, set())
        return capability_name in allowed

    def is_action_allowed(self, stage_id: str, action_kind: str, role: str | None) -> bool:
        """Return whether the role can invoke one action in a stage."""
        if role is None:
            return True

        allowed = self._action_permissions.get(role, set())
        return (stage_id, action_kind) in allowed

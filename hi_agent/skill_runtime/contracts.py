"""Skill runtime strategy protocols for the hi_agent platform layer.

These protocols define the strategy-layer contracts for skill execution,
resolution, and runtime management. They are intentionally separated from
the kernel DTO contracts to preserve kernel purity.

Note: DTO types (SkillDefinition, SkillRequest, SkillResult, SkillRuntimeHost)
are imported only under TYPE_CHECKING to avoid a circular dependency with
agent_kernel.skills.contracts which re-exports these protocols. The Protocol
method bodies remain abstract stubs (``...``) so runtime import is not needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agent_kernel.skills.contracts import (
        SkillDefinition,
        SkillRequest,
        SkillResult,
        SkillRuntimeHost,
    )

__all__ = [
    "LocalSkillRuntimeFactory",
    "ManagedSkillRuntime",
    "RemoteSkillGatewayFactory",
    "SkillRegistry",
    "SkillResolver",
    "SkillRuntime",
    "SkillRuntimeFactory",
    "SkillRuntimeHostFactory",
]


class SkillRegistry(Protocol):
    """Owns skill metadata and versioned bindings."""

    async def get(self, skill_id: str, version: str | None = None) -> SkillDefinition | None:
        """Retrieve one skill definition by id and optional version.

        Args:
            skill_id: Skill identifier to look up.
            version: Optional version constraint.

        Returns:
            Matching skill definition, or ``None`` if not found.

        """
        ...

    async def resolve_by_action(self, action_type: str) -> SkillDefinition | None:
        """Resolve one skill definition by action type.

        Args:
            action_type: Action type discriminator.

        Returns:
            Matching skill definition, or ``None`` if not found.

        """
        ...

    async def list_by_kind(self, skill_kind: str) -> list[SkillDefinition]:
        """List all registered skills matching a given kind.

        Args:
            skill_kind: Skill kind discriminator.

        Returns:
            List of matching skill definitions.

        """
        ...


class SkillResolver(Protocol):
    """Resolves which registered skill should execute one action."""

    async def resolve(
        self,
        action: object,
    ) -> SkillDefinition:
        """Resolve which registered skill should execute one action.

        Args:
            action: Action resolve input with type and preference hints.

        Returns:
            Resolved skill definition for the action.

        """
        ...


class SkillRuntime(Protocol):
    """Executes one skill request under executor governance."""

    async def execute(self, request: SkillRequest) -> SkillResult:
        """Execute one skill request and returns the result.

        Args:
            request: Skill execution request with action and input payload.

        Returns:
            Skill execution result with output or failure details.

        """
        ...


class ManagedSkillRuntime(SkillRuntime, Protocol):
    """Extends skill runtime with optional managed lifecycle hooks."""

    async def validate(self, request: SkillRequest) -> None:
        """Validate one request before execute.

        Args:
            request: The incoming request object.

        """
        ...

    async def warmup(self) -> None:
        """Warms up runtime resources."""
        ...

    async def shutdown(self) -> None:
        """Releases runtime resources."""
        ...


class SkillRuntimeFactory(Protocol):
    """Creates skill runtime instances from registered definitions."""

    async def create(self, definition: SkillDefinition) -> SkillRuntime:
        """Create one skill runtime from a registered definition.

        Args:
            definition: Skill definition governing the runtime instance.

        Returns:
            Initialized skill runtime ready for execution.

        """
        ...


class SkillRuntimeHostFactory(Protocol):
    """Creates runtimes by explicit host kind routing."""

    async def create_for_host(
        self,
        definition: SkillDefinition,
        host_kind: SkillRuntimeHost,
    ) -> SkillRuntime:
        """Create runtime for a concrete host kind.

        Args:
            definition: Skill definition governing the runtime instance.
            host_kind: Target host kind to create the runtime for.

        Returns:
            Initialized skill runtime for the requested host kind.

        """
        ...


class LocalSkillRuntimeFactory(Protocol):
    """Creates local-host skill runtimes."""

    async def create_cli_process(self, definition: SkillDefinition) -> SkillRuntime:
        """Create runtime for ``cli_process`` host.

        Args:
            definition: Skill definition governing the runtime instance.

        Returns:
            SkillRuntime: Initialized skill runtime instance.

        """
        ...

    async def create_in_process_python(self, definition: SkillDefinition) -> SkillRuntime:
        """Create runtime for ``in_process_python`` host.

        Args:
            definition: Skill definition governing the runtime instance.

        Returns:
            SkillRuntime: Initialized skill runtime instance.

        """
        ...


class RemoteSkillGatewayFactory(Protocol):
    """Creates remote-service skill gateway runtimes."""

    async def create_remote_service(self, definition: SkillDefinition) -> SkillRuntime:
        """Create runtime for ``remote_service`` host.

        Args:
            definition: Skill definition governing the runtime instance.

        Returns:
            Initialized remote-service skill runtime.

        """
        ...

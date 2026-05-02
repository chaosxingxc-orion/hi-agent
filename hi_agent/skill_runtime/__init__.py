"""Skill runtime strategy layer for the hi_agent platform.

Exports all strategy-layer skill Protocols from
:mod:`hi_agent.skill_runtime.contracts`. The concrete factory implementation
(``DefaultSkillRuntimeFactory``) is available from
:mod:`hi_agent.skill_runtime.runtime_factory` to avoid circular initialization.

DTO contracts (``SkillRequest``, ``SkillResult``, ``SkillDefinition``) remain in
:mod:`agent_kernel.skills.contracts`.

This package was renamed from ``hi_agent.skills`` to distinguish lifecycle
(``hi_agent.skill``) from runtime strategy (``hi_agent.skill_runtime``).
The legacy ``hi_agent.skills`` import path still works via a deprecation
shim and will be removed in Wave 34.
"""

from hi_agent.skill_runtime.contracts import (
    LocalSkillRuntimeFactory,
    ManagedSkillRuntime,
    RemoteSkillGatewayFactory,
    SkillRegistry,
    SkillResolver,
    SkillRuntime,
    SkillRuntimeFactory,
    SkillRuntimeHostFactory,
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

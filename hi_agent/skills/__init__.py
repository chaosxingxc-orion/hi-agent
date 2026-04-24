"""Skill runtime strategy layer for the hi_agent platform.

Exports all strategy-layer skill Protocols from hi_agent.skills.contracts.
The concrete factory implementation (DefaultSkillRuntimeFactory) is available
from hi_agent.skills.runtime_factory to avoid circular initialization.

DTO contracts (SkillRequest, SkillResult, SkillDefinition) remain in
agent_kernel.skills.contracts.
"""

from hi_agent.skills.contracts import (
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

"""Capability adapters for integrating external tool definitions."""

from hi_agent.capability.adapters.core_tool_adapter import CoreToolAdapter
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptorFactory

__all__ = [
    "CapabilityDescriptorFactory",
    "CoreToolAdapter",
]

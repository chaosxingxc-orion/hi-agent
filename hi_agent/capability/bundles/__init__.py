"""Capability bundles: pre-packaged collections of capabilities for specific domains.

Each bundle is a self-contained collection of CapabilitySpec entries that
can be registered into a CapabilityRegistry in a single call.

Usage::

    from hi_agent.capability.bundles.research import ResearchBundle
    from hi_agent.capability.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    bundle = ResearchBundle(llm_gateway=gateway)
    bundle.register(registry)
"""

from hi_agent.capability.bundles.base import CapabilityBundle

__all__ = ["CapabilityBundle"]

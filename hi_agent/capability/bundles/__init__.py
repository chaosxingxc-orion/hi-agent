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


def __getattr__(name: str) -> object:
    """Backward-compat shim for deprecated bundle exports."""
    if name == "ResearchBundle":
        import warnings

        warnings.warn(
            "ResearchBundle is deprecated and will be removed in Wave 14. "
            "Use a domain-neutral bundle name.",
            DeprecationWarning,
            stacklevel=2,
        )
        from examples.bundles.research import ResearchBundle

        return ResearchBundle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

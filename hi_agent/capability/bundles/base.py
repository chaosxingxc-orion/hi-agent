"""Base class for capability bundles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.capability.registry import CapabilityRegistry


class CapabilityBundle(ABC):
    """Base class for domain-specific capability bundles.

    Subclasses implement :meth:`register` to add a coherent set of
    domain-specific capabilities to a CapabilityRegistry.

    Example::

        class MyBundle(CapabilityBundle):
            def register(self, registry):
                registry.register(CapabilitySpec("my_tool", my_handler))

        bundle = MyBundle()
        bundle.register(registry)
    """

    @abstractmethod
    def register(self, registry: "CapabilityRegistry") -> int:
        """Register all capabilities in this bundle into the registry.

        Args:
            registry: The CapabilityRegistry to register into.

        Returns:
            Number of capabilities registered.
        """
        ...

    @property
    def name(self) -> str:
        """Bundle name — defaults to the class name."""
        return type(self).__name__

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

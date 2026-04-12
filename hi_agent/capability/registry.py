"""Capability registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilitySpec:
    """Capability metadata and callable entrypoint."""

    name: str
    handler: Callable[[dict], dict]
    description: str = ""
    parameters: dict = field(default_factory=dict)  # JSON Schema dict


class CapabilityRegistry:
    """In-memory capability registry."""

    def __init__(self) -> None:
        """Initialize empty capability map."""
        self._capabilities: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        """Register or replace capability by name."""
        self._capabilities[spec.name] = spec

    def get(self, name: str) -> CapabilitySpec:
        """Get capability by name."""
        if name not in self._capabilities:
            raise KeyError(f"Unknown capability: {name}")
        return self._capabilities[name]

    def list_names(self) -> list[str]:
        """List registered capability names."""
        return sorted(self._capabilities.keys())

    def register_bundle(self, bundle: "Any") -> int:
        """Register all capabilities from a CapabilityBundle.

        Args:
            bundle: A CapabilityBundle instance with a register(registry) method.

        Returns:
            Number of capabilities registered by the bundle.
        """
        return bundle.register(self)

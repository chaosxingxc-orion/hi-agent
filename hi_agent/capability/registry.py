"""Capability registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilitySpec:
    """Capability metadata and callable entrypoint."""

    name: str
    handler: Callable[[dict], dict]


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

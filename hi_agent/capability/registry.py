"""Capability registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

RiskClass = Literal[
    "read_only", "filesystem_read", "filesystem_write", "network", "shell", "credential"
]


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Machine-readable risk metadata for a capability."""

    name: str
    risk_class: RiskClass = "read_only"
    side_effect_class: str = "none"
    remote_callable: bool = True
    prod_enabled_default: bool = True
    requires_auth: bool = True
    requires_approval: bool = False
    required_env: dict[str, str] = field(default_factory=dict)  # {env_var: description}
    output_budget_chars: int = 32_000
    availability_probe: Callable[[], tuple[bool, str]] | None = None
    # Wave 8 / P2.1: capability policy fields for downstream research platform
    source_reference_policy: str = "optional"  # "required" | "optional" | "none"
    artifact_output_schema: str | None = None
    provenance_required: bool = False
    reproducibility_level: str = "stochastic"  # "deterministic" | "seeded" | "stochastic"
    license_policy: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CapabilitySpec:
    """Capability metadata and callable entrypoint."""

    name: str
    handler: Callable[[dict], dict]
    description: str = ""
    parameters: dict = field(default_factory=dict)  # JSON Schema dict
    descriptor: CapabilityDescriptor | None = None


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
            available = list(self._capabilities.keys())
            raise KeyError(f"Unknown capability: {name!r}. Available: {available}")
        return self._capabilities[name]

    def list_names(self) -> list[str]:
        """List registered capability names."""
        return sorted(self._capabilities.keys())

    def register_bundle(self, bundle: Any) -> int:
        """Register all capabilities from a CapabilityBundle.

        Args:
            bundle: A CapabilityBundle instance with a register(registry) method.

        Returns:
            Number of capabilities registered by the bundle.
        """
        return bundle.register(self)

    def get_descriptor(self, name: str) -> CapabilityDescriptor | None:
        """Return the CapabilityDescriptor for a registered capability, or None."""
        spec = self._capabilities.get(name)
        if spec is None:
            return None
        return spec.descriptor

    def probe_availability(self, name: str) -> tuple[bool, str]:
        """Check if a capability is available given current environment.

        Checks:
        1. required_env — all keys must be present in os.environ
        2. availability_probe() — if defined, calls it and uses result

        Returns:
            (True, "") if available
            (False, reason) if unavailable
        """
        import os

        if name not in self._capabilities:
            return False, f"capability {name!r} not registered"

        spec = self._capabilities[name]
        descriptor = spec.descriptor
        if descriptor is None:
            return True, ""

        # Check required_env
        for env_var, env_desc in descriptor.required_env.items():
            if not os.environ.get(env_var):
                return False, f"missing env var {env_var!r} ({env_desc})"

        # Call availability_probe if present
        probe = descriptor.availability_probe
        if probe is not None and callable(probe):
            try:
                ok, reason = probe()
                if not ok:
                    return False, reason
            except Exception as e:
                return False, f"availability_probe raised: {e}"

        return True, ""

    def list_with_views(self) -> list[tuple]:
        """List capabilities with availability status for manifest rendering.

        Returns list of (name, descriptor, status, reason) tuples where:
            status: "available" | "unavailable" | "not_wired"
            reason: empty string if available, else explanation
        """
        result = []
        for name in sorted(self._capabilities.keys()):
            spec = self._capabilities[name]
            desc = spec.descriptor
            ok, reason = self.probe_availability(name)
            status = "available" if ok else "unavailable"
            result.append((name, desc, status, reason))
        return result

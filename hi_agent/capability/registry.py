"""Capability registry."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from hi_agent.observability.metric_counter import Counter

_logger = logging.getLogger(__name__)
_registry_errors_total = Counter("hi_agent_capability_registry_errors_total")
_capability_posture_denied_total = Counter("hi_agent_capability_posture_denied_total")


class CapabilityNotAvailableError(Exception):
    """Raised when a capability is not available under the active posture.

    Distinct from :class:`hi_agent.capability.invoker.CapabilityUnavailableError`
    (which signals env-var / availability-probe failure).  This error signals
    a posture-policy denial: the capability is registered and probe-clean, but
    its descriptor's ``available_in_<posture>`` field is ``False`` for the
    posture under which dispatch was attempted (e.g. ``shell_exec`` under
    ``prod``).

    The error carries a structured 400 envelope (compatible with
    ``hi_agent.server.error_categories.error_response``) so HTTP boundaries
    can surface it without string-matching.
    """

    def __init__(self, capability_name: str, posture: str, reason: str = "") -> None:
        """Initialize posture-denial details.

        Args:
            capability_name: The capability that was attempted.
            posture: The posture under which it was rejected ("dev"/"research"/"prod").
            reason: Optional human-readable extra detail.
        """
        self.capability_name = capability_name
        self.posture = posture
        self.reason = reason or (
            f"capability {capability_name!r} is not available in {posture!r} posture"
        )
        super().__init__(self.reason)

    def to_envelope(self) -> dict:
        """Return a structured error envelope (HTTP 400 mapping).

        Shape matches :func:`hi_agent.server.error_categories.error_response`
        with ``error_category='invalid_request'`` and ``retryable=False``;
        downstream callers can flip posture or pick a different capability.
        """
        return {
            "error_category": "invalid_request",
            "message": self.reason,
            "retryable": False,
            "next_action": (
                f"capability {self.capability_name!r} is not permitted under "
                f"posture {self.posture!r}; choose a different capability or "
                "lower the posture if the operator policy allows it"
            ),
            "capability_name": self.capability_name,
            "posture": self.posture,
        }


RiskClass = Literal[
    "read_only", "filesystem_read", "filesystem_write", "network", "shell", "credential"
]


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Machine-readable risk metadata for a capability.

    This is the single canonical definition.  Fields from two historical
    sources are unified here:
    - Platform governance fields (risk_class, side_effect_class, …)
    - Adapter/factory fields (effect_class, tags, sandbox_level, …)

    Use build_capability_view() from descriptor_factory to produce
    the dict shape consumed by the adapter layer.
    """

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
    # CO-6: adapter/factory fields (from descriptor_factory.py, now canonical here)
    effect_class: str = "unknown_effect"   # read_only | idempotent_write | irreversible_write
    tags: tuple[str, ...] = ()
    sandbox_level: str = "none"
    description: str = ""
    parameters: dict = field(default_factory=dict)   # JSON Schema dict for the capability
    extra: dict = field(default_factory=dict)        # catch-all for additional metadata
    toolset_id: str = "default"
    output_budget_tokens: int = 0  # 0 = unlimited
    maturity_level: Literal["L0", "L1", "L2", "L3", "L4"] = "L1"
    # W22-A9: per-capability posture matrix
    available_in_dev: bool = True
    available_in_research: bool = True
    available_in_prod: bool = True


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
                _registry_errors_total.inc()
                _logger.warning(
                    "registry.availability_probe_error name=%s error=%s",
                    name if "name" in dir() else "unknown", e,
                )
                return False, f"availability_probe raised: {e}"

        return True, ""

    def probe_availability_with_posture(self, name: str, *, posture: str) -> bool:
        """Assert *name* is available under *posture*; raise on denial.

        Extends :meth:`probe_availability` with posture-aware field checks
        keyed off ``CapabilityDescriptor.available_in_{dev,research,prod}``.

        Args:
            name: Capability name.
            posture: One of ``"dev"``, ``"research"``, ``"prod"``.

        Returns:
            ``True`` if the capability is registered, env-clean, and permitted
            under *posture*.

        Raises:
            CapabilityNotAvailableError: When the capability's descriptor has
                ``available_in_<posture>=False``, when the underlying
                ``probe_availability`` check fails (env / probe denial), or
                when the capability is not registered.  The exception carries
                a structured 400 envelope (``to_envelope()``) for HTTP
                surfaces.
        """
        ok, reason = self.probe_availability(name)
        if not ok:
            _capability_posture_denied_total.inc()
            _logger.warning(
                "registry.posture_denied name=%s posture=%s reason=%s",
                name, posture, reason,
            )
            raise CapabilityNotAvailableError(name, posture, reason)

        spec = self._capabilities.get(name)
        if spec is None:
            _capability_posture_denied_total.inc()
            _logger.warning(
                "registry.posture_denied name=%s posture=%s reason=not_registered",
                name, posture,
            )
            raise CapabilityNotAvailableError(
                name, posture, f"capability {name!r} not registered"
            )
        desc = spec.descriptor
        if desc is None:
            return True

        field_map = {
            "dev": "available_in_dev",
            "research": "available_in_research",
            "prod": "available_in_prod",
        }
        field_name = field_map.get(posture)
        if field_name is not None and not getattr(desc, field_name, True):
            _capability_posture_denied_total.inc()
            _logger.warning(
                "registry.posture_denied name=%s posture=%s reason=descriptor_field_false",
                name, posture,
            )
            raise CapabilityNotAvailableError(name, posture)

        return True

    def to_extension_manifest_dict(self, name: str) -> dict:
        """Return a dict conforming to the ExtensionManifest shape for *name*.

        Converts the CapabilityDescriptor registered under *name* into the
        unified extension-manifest dict shape without changing any existing
        interface.  Returns an empty dict if *name* is not registered.

        The ``posture_support`` sub-dict reads each descriptor's
        ``available_in_{dev,research,prod}`` fields directly — it is NOT a
        hardcoded ``{dev:True, research:True, prod:True}`` constant.  See
        Track D of W24 for the rationale and regression test.
        """
        spec = self._capabilities.get(name)
        if spec is None:
            return {}
        desc = spec.descriptor
        return {
            "name": name,
            "version": "1.0",
            "kind": "kernel",
            "schema_version": "1.0",
            "posture_support": {
                "dev": getattr(desc, "available_in_dev", True) if desc else True,
                "research": getattr(desc, "available_in_research", True) if desc else True,
                "prod": getattr(desc, "available_in_prod", True) if desc else True,
            },
            "effect_class": getattr(desc, "effect_class", "unknown_effect")
            if desc
            else "unknown_effect",
            "risk_class": getattr(desc, "risk_class", "read_only") if desc else "read_only",
            "description": getattr(desc, "description", "") if desc else "",
        }

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

"""Capability subsystem exports.

W31 T-6' decision (process-internal annotation):

CapabilitySpec and CapabilityDescriptor are platform-level metadata for
tools (read_file, http_request, llm_completion, ...) that are available to
every tenant equally.  They do not carry tenant_id because the platform
operator owns the capability surface; tenant-specific override or denial
lives above this layer (in route handlers / policy gates / posture flags),
not on the registry row.

If a future requirement calls for per-tenant capability registration (e.g.
tenant-uploaded plugin tools), the right model is a separate
TenantCapabilityOverlay table layered on top of the platform registry — it
is not adding tenant_id to CapabilitySpec.

The contract-spine completeness gate
(``scripts/check_contract_spine_completeness.py``) recognises the
``# scope: process-internal`` marker on these classes and exempts them from
the tenant_id requirement.
"""

from hi_agent.capability.adapters import CapabilityDescriptorFactory, CoreToolAdapter
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor
from hi_agent.capability.async_invoker import AsyncCapabilityInvoker
from hi_agent.capability.circuit_breaker import CircuitBreaker, CircuitState
from hi_agent.capability.defaults import register_default_capabilities
from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.policy import CapabilityPolicy
from hi_agent.capability.registry import (
    CapabilityNotAvailableError,
    CapabilityRegistry,
    CapabilitySpec,
)

__all__ = [
    "AsyncCapabilityInvoker",
    "CapabilityDescriptor",
    "CapabilityDescriptorFactory",
    "CapabilityInvoker",
    "CapabilityNotAvailableError",
    "CapabilityPolicy",
    "CapabilityRegistry",
    "CapabilitySpec",
    "CircuitBreaker",
    "CircuitState",
    "CoreToolAdapter",
    "register_default_capabilities",
]

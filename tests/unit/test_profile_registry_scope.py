"""Unit tests for ProfileRegistry process-internal scope (W32 Track B, Gap 1).

The ProfileRegistry is documented as process-internal — profile schemas are
loaded from the filesystem and shared across all tenants in the worker
process. Per-tenant profile selection happens at the consumer side via
``task_contract.profile_id``. This test pins the documented invariant:

1. The class body carries the ``# scope: process-internal`` annotation
   explaining the deliberate global scope.
2. ``register`` and ``get`` operate on global state (no tenant kwarg, no
   tenant-keyed partitioning).

Layer 1 — Unit: pure ProfileRegistry, no real dependencies on filesystem
or downstream consumers.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.registry import ProfileRegistry


class TestProfileRegistryScopeAnnotation:
    """The class body must carry the ``# scope: process-internal`` marker."""

    def test_class_body_carries_scope_annotation(self) -> None:
        """The annotation must appear inline in the class body."""
        src = Path(inspect.getsourcefile(ProfileRegistry)).read_text(encoding="utf-8")
        assert "# scope: process-internal" in src, (
            "ProfileRegistry must carry an inline `# scope: process-internal` "
            "comment documenting that profile schemas are filesystem-loaded and "
            "shared across tenants in the worker process. See W32 Track B Gap 1."
        )

    def test_class_signature_does_not_take_tenant_id(self) -> None:
        """register/get/has/remove must NOT accept a tenant_id kwarg.

        The whole point of the process-internal annotation is that there is
        no per-tenant scoping at this layer. If a kwarg appears, the
        documented invariant is broken.
        """
        for method_name in ("register", "get", "has", "remove"):
            method = getattr(ProfileRegistry, method_name)
            sig = inspect.signature(method)
            assert "tenant_id" not in sig.parameters, (
                f"ProfileRegistry.{method_name} must NOT accept tenant_id; "
                f"the class is documented process-internal. See W32 Track B Gap 1."
            )


class TestProfileRegistryGlobalState:
    """register/get must operate on global state (no tenant scoping)."""

    def test_register_then_get_returns_same_instance(self) -> None:
        """A registered profile is retrievable by id without tenant filtering."""
        reg = ProfileRegistry()
        spec = ProfileSpec(profile_id="p-1", display_name="Profile 1")
        reg.register(spec)
        retrieved = reg.get("p-1")
        assert retrieved is spec

    def test_two_callers_observe_same_global_state(self) -> None:
        """A single registry instance carries one global namespace.

        We register from one logical caller and read from another with no
        tenant_id arg — the documented invariant is "shared across tenants
        in the worker process".
        """
        reg = ProfileRegistry()
        spec = ProfileSpec(profile_id="p-shared", display_name="Shared")
        reg.register(spec)

        # "Tenant A" reads — no tenant filter.
        assert reg.has("p-shared") is True
        # "Tenant B" reads the same instance — no tenant filter; same view.
        assert reg.get("p-shared") is spec
        # Count is global.
        assert reg.count() == 1

    def test_register_collision_on_duplicate_profile_id(self) -> None:
        """Register raises on duplicate id regardless of any caller identity.

        This is the deliberate global-namespace behaviour: there is no
        per-tenant slot to disambiguate two profiles with the same id.
        """
        import pytest

        reg = ProfileRegistry()
        spec = ProfileSpec(profile_id="p-dup", display_name="Dup")
        reg.register(spec)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(spec)

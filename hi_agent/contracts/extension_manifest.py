"""ExtensionManifest Protocol and ExtensionRegistry.

Provides full validation on register() and a fail-closed enable() gate.
ExtensionDisallowedError is raised when an extension is blocked.

# scope: process-internal for ExtensionRegistry state (_manifests, _enabled)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hi_agent.config.posture import Posture

logger = logging.getLogger(__name__)


class ExtensionDisallowedError(Exception):
    """Raised when ExtensionRegistry.enable() blocks an extension.

    Attributes:
        reasons: Human-readable list of reasons the extension was blocked.
    """

    def __init__(self, message: str, reasons: list[str] | None = None) -> None:
        super().__init__(message)
        self.reasons: list[str] = reasons if reasons is not None else []


class ExtensionRequiresHumanApproval(ExtensionDisallowedError):  # noqa: N818  expiry_wave: Wave 17
    """Raised when a dangerous extension requires human gate approval to enable."""

    def __init__(self, name: str, version: str, dangerous_capabilities: list[str]) -> None:
        self.extension_name = name
        self.extension_version = version
        self.dangerous_capabilities = dangerous_capabilities
        super().__init__(
            f"Extension '{name}' v{version} requires human gate approval "
            f"(dangerous_capabilities: {dangerous_capabilities})",
            reasons=[
                f"dangerous_capabilities={dangerous_capabilities!r}; "
                "human gate approval required under strict posture"
            ],
        )


class ExtensionTenantScopeRequired(ExtensionDisallowedError):  # noqa: N818  expiry_wave: Wave 17
    """Raised when enabling an extension with tenant_scope requires a non-empty tenant_id."""

    def __init__(self, name: str, version: str, tenant_scope: str) -> None:
        self.extension_name = name
        self.extension_version = version
        self.tenant_scope = tenant_scope
        super().__init__(
            f"Extension '{name}' v{version} has tenant_scope='{tenant_scope}' "
            f"but was enabled without a tenant_id",
            reasons=[
                f"tenant_scope={tenant_scope!r} requires a non-empty tenant_id at enable() time"
            ],
        )


@runtime_checkable
class ExtensionManifest(Protocol):
    """Descriptor Protocol for a hi-agent extension (plugin, kernel, mcp_tool, knowledge).

    Core fields:
        name: Unique extension name.
        version: Semantic version string.
        manifest_kind: "plugin" | "kernel" | "mcp_tool" | "knowledge"
        schema_version: Integer schema version (bump when fields change).
        posture_support: Map of posture name to supported flag.

    Enforcement fields:
        required_posture: Minimum posture required to enable this extension.
            "any" | "dev" | "strict" | "prod"  ("research" is deprecated; Wave 24 removal)
        tenant_scope: Isolation scope of this extension.
            "global" | "tenant" | "user" | "session"
        dangerous_capabilities: List of dangerous capability tags, e.g.
            ["filesystem_write", "network_egress"]. Empty = no danger flags.
        config_schema: JSON Schema dict for extension config, or None if the
            extension requires no config.
    """

    # -- Core fields --
    name: str
    version: str
    manifest_kind: str
    schema_version: int
    posture_support: dict[str, bool]

    # -- Enforcement fields --
    required_posture: str  # "any" | "dev" | "strict" | "prod"  ("research" deprecated Wave 24)
    tenant_scope: str  # "global" | "tenant" | "user" | "session"
    dangerous_capabilities: list[str]  # e.g. ["filesystem_write", "network_egress"]
    config_schema: dict | None  # JSON Schema for config; None = no config required

    def to_manifest_dict(self) -> dict: ...

    def production_eligibility(self, posture: Posture) -> tuple[bool, list[str]]:
        """Return (eligible, reasons_blocked) for this extension under the given posture."""
        ...


class ExtensionManifestMixin:
    """Mixin that provides a default production_eligibility() implementation.

    Concrete manifests should inherit from this mixin to avoid duplicating
    the eligibility logic.  The mixin reads the four enforcement fields that
    every ExtensionManifest is required to carry.
    """

    # These attributes must be declared on the concrete class.
    required_posture: str
    tenant_scope: str
    dangerous_capabilities: list[str]
    config_schema: dict | None

    def production_eligibility(self, posture: Posture) -> tuple[bool, list[str]]:
        """Check production eligibility based on posture and enforcement fields.

        Rules (applied in order):
        1. If required_posture == "prod" and posture is DEV  -> blocked.
        2. If required_posture == "research" and posture is DEV -> blocked.
        3. If posture.is_strict and config_schema is None and
           dangerous_capabilities is non-empty -> blocked
           (dangerous extension requires explicit config schema under strict posture).

        Returns:
            (True, []) when eligible.
            (False, [reason1, ...]) when blocked.
        """
        import warnings

        from hi_agent.config.posture import Posture as _Posture

        blocked: list[str] = []

        rp = getattr(self, "required_posture", "any")
        dc = getattr(self, "dangerous_capabilities", [])
        cs = getattr(self, "config_schema", None)

        # Deprecation: "research" is a legacy alias for "strict"; map it and warn.
        if rp == "research":
            warnings.warn(
                "required_posture='research' is deprecated and will be removed in Wave 24. "
                "Use 'strict' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            rp = "strict"

        if rp == "prod" and posture == _Posture.DEV:
            blocked.append(
                f"required_posture={rp!r} but current posture is 'dev'; "
                "this extension requires prod deployment"
            )
        elif rp == "strict" and posture == _Posture.DEV:
            blocked.append(
                f"required_posture={rp!r} but current posture is 'dev'; "
                "this extension requires strict or prod deployment"
            )

        if posture.is_strict and cs is None and dc:
            blocked.append(
                f"posture={posture.value!r} (strict) but config_schema is None "
                f"and dangerous_capabilities={dc!r}; "
                "dangerous extensions must declare a config_schema under strict posture"
            )

        return (len(blocked) == 0, blocked)


_VALID_MANIFEST_KINDS = frozenset({"plugin", "kernel", "mcp_tool", "knowledge"})
_VALID_REQUIRED_POSTURES = frozenset({"any", "dev", "research", "prod"})
_VALID_TENANT_SCOPES = frozenset({"global", "tenant", "user", "session"})


class ExtensionRegistry:
    """Validated registry for ExtensionManifest instances.

    Replaces the bare dict with full validation on register() and a
    fail-closed enable() gate.

    # scope: process-internal
    """

    def __init__(self) -> None:
        self._manifests: dict[str, ExtensionManifest] = {}
        self._enabled: set[str] = set()
        # key: (name, version, tenant_id) -> gate_decision_id
        self._human_gate_approvals: dict[tuple[str, str, str], str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, manifest: ExtensionManifest, posture: Posture | None = None) -> None:
        """Register a manifest with full validation.

        Under dev posture, manifests missing the new enforcement fields receive
        defaults and a WARNING log instead of hard rejection.  Under research/prod,
        missing enforcement fields cause immediate ValueError.

        Args:
            manifest: The ExtensionManifest to register.
            posture: Current deployment posture.  None defaults to dev-permissive.

        Raises:
            ValueError: If manifest fails validation under the current posture.
        """
        from hi_agent.config.posture import Posture as _Posture

        effective_posture = posture if posture is not None else _Posture.DEV

        # --- Validate manifest_kind ---
        kind = getattr(manifest, "manifest_kind", None)
        if kind not in _VALID_MANIFEST_KINDS:
            raise ValueError(
                f"Invalid manifest_kind={kind!r} for extension "
                f"{getattr(manifest, 'name', '?')!r}; "
                f"must be one of {sorted(_VALID_MANIFEST_KINDS)}"
            )

        name = getattr(manifest, "name", None)
        version = getattr(manifest, "version", None)
        if not name or not version:
            raise ValueError("ExtensionManifest must have non-empty name and version fields")

        key = f"{name}:{version}"

        # --- Duplicate guard ---
        if key in self._manifests:
            raise ValueError(
                f"Extension {key!r} already registered; silent overwrite is forbidden. "
                "Deregister the existing entry first."
            )

        # --- posture_support must be non-empty ---
        posture_support = getattr(manifest, "posture_support", None)
        if not posture_support:
            raise ValueError(
                f"Extension {key!r} has empty posture_support; "
                "declare at least one posture entry."
            )

        # --- Enforcement fields: strict vs permissive ---
        self._validate_enforcement_fields(manifest, key, effective_posture)

        self._manifests[key] = manifest
        logger.info(
            "ExtensionRegistry.register: registered extension %r (kind=%r, posture=%r)",
            key,
            kind,
            effective_posture.value,
        )

    def _validate_enforcement_fields(
        self,
        manifest: ExtensionManifest,
        key: str,
        posture: Posture,
    ) -> None:
        """Validate the four enforcement fields.

        Under dev posture: missing/invalid fields are warned but not fatal.
        Under research/prod: missing/invalid fields raise ValueError.
        """
        issues: list[str] = []

        # required_posture
        rp = getattr(manifest, "required_posture", None)
        if rp is None:
            issues.append("missing required_posture field")
        elif rp not in _VALID_REQUIRED_POSTURES:
            valid = sorted(_VALID_REQUIRED_POSTURES)
            issues.append(f"invalid required_posture={rp!r}; must be one of {valid}")

        # tenant_scope
        ts = getattr(manifest, "tenant_scope", None)
        if ts is None:
            issues.append("missing tenant_scope field")
        elif ts not in _VALID_TENANT_SCOPES:
            valid_scopes = sorted(_VALID_TENANT_SCOPES)
            issues.append(f"invalid tenant_scope={ts!r}; must be one of {valid_scopes}")

        # dangerous_capabilities (must be a list, may be empty)
        dc = getattr(manifest, "dangerous_capabilities", None)
        if dc is None:
            issues.append("missing dangerous_capabilities field (use [] for no dangerous caps)")

        # config_schema (None is valid)
        if not hasattr(manifest, "config_schema"):
            issues.append("missing config_schema field (use None if no config is required)")

        if not issues:
            return

        if posture.is_strict:
            raise ValueError(
                f"Extension {key!r} failed enforcement field validation under "
                f"posture={posture.value!r}: {'; '.join(issues)}"
            )
        else:
            logger.warning(
                "ExtensionRegistry: extension %r has enforcement field issues (dev posture — "
                "allowed, but will fail under research/prod): %s",
                key,
                "; ".join(issues),
            )

    # ------------------------------------------------------------------
    # Human gate approvals
    # ------------------------------------------------------------------

    def approve_via_human_gate(
        self,
        name: str,
        version: str,
        *,
        tenant_id: str,
        approver_user_id: str,
        gate_decision_id: str,
    ) -> None:
        """Record human gate approval for this (extension, version, tenant) triple.

        Args:
            name: Extension name.
            version: Extension version.
            tenant_id: Tenant for which approval is granted.
            approver_user_id: User ID of the approver.
            gate_decision_id: Opaque ID of the gate decision record.
        """
        self._human_gate_approvals[(name, version, tenant_id)] = gate_decision_id
        logger.info(
            "ExtensionRegistry.approve_via_human_gate: approved %r v%s for tenant=%r "
            "(approver=%r, gate_decision_id=%r)",
            name,
            version,
            tenant_id,
            approver_user_id,
            gate_decision_id,
        )

    # ------------------------------------------------------------------
    # Enable gate
    # ------------------------------------------------------------------

    def enable(self, name: str, version: str, posture: Posture | None = None, *, tenant_id: str = "") -> None:  # noqa: E501  expiry_wave: Wave 17
        """Fail-closed gate: check production_eligibility before enabling.

        Args:
            name: Extension name.
            version: Extension version.
            posture: Current deployment posture.  None defaults to Posture.from_env().
            tenant_id: Tenant context for scoped extensions.  Required for
                extensions with tenant_scope in ("tenant", "user", "session").

        Raises:
            KeyError: If the extension is not registered.
            ExtensionDisallowedError: If production_eligibility returns not-eligible.
            ExtensionTenantScopeRequired: If tenant_scope requires a non-empty tenant_id.
            ExtensionRequiresHumanApproval: If dangerous_capabilities present under strict
                posture and no human gate approval has been recorded.
        """
        from hi_agent.config.posture import Posture as _Posture

        effective_posture = posture if posture is not None else _Posture.from_env()

        key = f"{name}:{version}"
        manifest = self._manifests.get(key)
        if manifest is None:
            raise KeyError(f"ExtensionRegistry.enable: extension {key!r} is not registered")

        # --- tenant_scope check ---
        tenant_scope = getattr(manifest, "tenant_scope", "global")
        if tenant_scope in ("tenant", "user", "session") and not tenant_id:
            raise ExtensionTenantScopeRequired(name, version, tenant_scope)

        # --- dangerous_capabilities human gate check (strict posture only) ---
        dangerous = getattr(manifest, "dangerous_capabilities", [])
        if dangerous and effective_posture.is_strict:
            approval_key = (name, version, tenant_id)
            if approval_key not in self._human_gate_approvals:
                raise ExtensionRequiresHumanApproval(name, version, dangerous)

        if not hasattr(manifest, "production_eligibility"):
            # Fallback for old manifests missing the method — allow under dev, block under strict.
            if effective_posture.is_strict:
                raise ExtensionDisallowedError(
                    f"Extension {key!r} does not implement production_eligibility(); "
                    f"blocked under strict posture={effective_posture.value!r}",
                    reasons=["missing production_eligibility() method on manifest"],
                )
            logger.warning(
                "ExtensionRegistry.enable: extension %r missing production_eligibility(); "
                "allowing under dev posture.",
                key,
            )
            self._enabled.add(key)
            return

        eligible, reasons = manifest.production_eligibility(effective_posture)
        if not eligible:
            raise ExtensionDisallowedError(
                f"Extension {key!r} blocked by production_eligibility gate: {reasons}",
                reasons=reasons,
            )

        self._enabled.add(key)
        logger.info(
            "ExtensionRegistry.enable: extension %r enabled under posture=%r tenant_id=%r",
            key,
            effective_posture.value,
            tenant_id,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_enabled(self, name: str, version: str) -> bool:
        """Return True if the extension has been enabled via enable()."""
        return f"{name}:{version}" in self._enabled

    def list_manifests(self) -> list[ExtensionManifest]:
        """Return all registered manifests."""
        return list(self._manifests.values())

    def get(self, name: str, version: str) -> ExtensionManifest | None:
        """Return the manifest for the given name:version, or None."""
        return self._manifests.get(f"{name}:{version}")

    def lookup(self, name: str) -> ExtensionManifest | None:
        """Return the first registered manifest with the given name, or None."""
        for key, manifest in self._manifests.items():
            if key.startswith(f"{name}:"):
                return manifest
        return None

    def list_all(self) -> list[ExtensionManifest]:
        """Return all registered manifests (alias for list_manifests)."""
        return list(self._manifests.values())

    def list_by_kind(self, kind: str) -> list[ExtensionManifest]:
        """Return manifests whose manifest_kind matches kind."""
        return [m for m in self._manifests.values() if getattr(m, "manifest_kind", "") == kind]

    def list_for_posture(self, posture: str) -> list[ExtensionManifest]:
        """Return manifests that support the given posture."""
        result = []
        for m in self._manifests.values():
            support = getattr(m, "posture_support", {})
            if support.get(posture, True):
                result.append(m)
        return result

    def __len__(self) -> int:
        return len(self._manifests)


_GLOBAL_REGISTRY: ExtensionRegistry | None = None


def get_extension_registry() -> ExtensionRegistry:
    """Return the process-global ExtensionRegistry singleton."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ExtensionRegistry()
    return _GLOBAL_REGISTRY

"""ExtensionManifest Protocol and ExtensionRegistry.

Wave 10.5 W5-F: Adds 4 enforcement fields, validated register(), fail-closed
enable() gate, and ExtensionDisallowedError exception.

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

    def __init__(self, message: str, reasons: list[str]) -> None:
        super().__init__(message)
        self.reasons: list[str] = reasons


@runtime_checkable
class ExtensionManifest(Protocol):
    """Descriptor Protocol for a hi-agent extension (plugin, kernel, mcp_tool, knowledge).

    Existing fields (Wave 10.4):
        name: Unique extension name.
        version: Semantic version string.
        manifest_kind: "plugin" | "kernel" | "mcp_tool" | "knowledge"
        schema_version: Integer schema version (bump when fields change).
        posture_support: Map of posture name to supported flag.

    Enforcement fields (Wave 10.5 W5-F):
        required_posture: Minimum posture required to enable this extension.
            "any" | "dev" | "research" | "prod"
        tenant_scope: Isolation scope of this extension.
            "global" | "tenant" | "user" | "session"
        dangerous_capabilities: List of dangerous capability tags, e.g.
            ["filesystem_write", "network_egress"]. Empty = no danger flags.
        config_schema: JSON Schema dict for extension config, or None if the
            extension requires no config.
    """

    # -- Existing fields (Wave 10.4, keep as-is) --
    name: str
    version: str
    manifest_kind: str
    schema_version: int
    posture_support: dict[str, bool]

    # -- Enforcement fields (Wave 10.5 W5-F) --
    required_posture: str  # "any" | "dev" | "research" | "prod"
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
    every ExtensionManifest is required to carry (Wave 10.5 W5-F).
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
        from hi_agent.config.posture import Posture as _Posture

        blocked: list[str] = []

        rp = getattr(self, "required_posture", "any")
        dc = getattr(self, "dangerous_capabilities", [])
        cs = getattr(self, "config_schema", None)

        if rp == "prod" and posture == _Posture.DEV:
            blocked.append(
                f"required_posture={rp!r} but current posture is 'dev'; "
                "this extension requires prod deployment"
            )
        elif rp == "research" and posture == _Posture.DEV:
            blocked.append(
                f"required_posture={rp!r} but current posture is 'dev'; "
                "this extension requires research or prod deployment"
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

    Wave 10.5 W5-F: replaces the bare dict from Wave 10.4 with full validation
    on register() and a fail-closed enable() gate.

    # scope: process-internal
    """

    def __init__(self) -> None:
        self._manifests: dict[str, ExtensionManifest] = {}
        self._enabled: set[str] = set()

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
    # Enable gate
    # ------------------------------------------------------------------

    def enable(self, name: str, version: str, posture: Posture) -> None:
        """Fail-closed gate: check production_eligibility before enabling.

        Args:
            name: Extension name.
            version: Extension version.
            posture: Current deployment posture.

        Raises:
            KeyError: If the extension is not registered.
            ExtensionDisallowedError: If production_eligibility returns not-eligible.
        """
        key = f"{name}:{version}"
        manifest = self._manifests.get(key)
        if manifest is None:
            raise KeyError(f"ExtensionRegistry.enable: extension {key!r} is not registered")

        if not hasattr(manifest, "production_eligibility"):
            # Fallback for old manifests missing the method — allow under dev, block under strict.
            if posture.is_strict:
                raise ExtensionDisallowedError(
                    f"Extension {key!r} does not implement production_eligibility(); "
                    f"blocked under strict posture={posture.value!r}",
                    reasons=["missing production_eligibility() method on manifest"],
                )
            logger.warning(
                "ExtensionRegistry.enable: extension %r missing production_eligibility(); "
                "allowing under dev posture.",
                key,
            )
            self._enabled.add(key)
            return

        eligible, reasons = manifest.production_eligibility(posture)
        if not eligible:
            raise ExtensionDisallowedError(
                f"Extension {key!r} blocked by production_eligibility gate: {reasons}",
                reasons=reasons,
            )

        self._enabled.add(key)
        logger.info(
            "ExtensionRegistry.enable: extension %r enabled under posture=%r",
            key,
            posture.value,
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

    def __len__(self) -> int:
        return len(self._manifests)

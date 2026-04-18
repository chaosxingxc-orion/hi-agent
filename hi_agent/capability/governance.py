"""GovernedToolExecutor — central governance gate for all tool calls (P0-1b).

Every tool invocation from HTTP API, MCP protocol, runner, and CLI must flow
through GovernedToolExecutor before reaching CapabilityInvoker.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hi_agent.security.path_policy import PathPolicyViolation, safe_resolve
from hi_agent.security.url_policy import URLPolicy, URLPolicyViolation

if TYPE_CHECKING:
    from hi_agent.capability.invoker import CapabilityInvoker
    from hi_agent.capability.registry import CapabilityRegistry

_logger = logging.getLogger(__name__)


@dataclass
class GovernanceDecision:
    decision: Literal["allow", "deny", "approval_required"]
    reason: str | None = None


# ---------------------------------------------------------------------------
# Typed governance exceptions
# ---------------------------------------------------------------------------


class CapabilityDisabledError(Exception):
    """Capability is disabled in the current runtime profile."""


class CapabilityNotFoundError(Exception):
    """Capability name is not registered."""


class CapabilityUnavailableError(Exception):
    """Capability required_env is not satisfied."""


class PermissionDeniedError(Exception):
    """Principal lacks required permission for this capability."""


class ApprovalRequiredError(Exception):
    """Capability requires explicit approval before execution."""

    def __init__(self, message: str, capability_name: str) -> None:
        super().__init__(message)
        self.capability_name = capability_name


class PolicyViolationError(Exception):
    """Argument failed PathPolicy or URLPolicy check."""


# ---------------------------------------------------------------------------
# GovernedToolExecutor
# ---------------------------------------------------------------------------


class GovernedToolExecutor:
    """Governance-gated wrapper around CapabilityInvoker.

    Enforces descriptor-based rules (prod_enabled_default, required_env,
    requires_auth, requires_approval) before delegating to the real invoker.
    Writes an audit record for every decision when audit_store is configured.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        invoker: CapabilityInvoker,
        runtime_mode: str = "dev-smoke",
        audit_store: object | None = None,
    ) -> None:
        self._registry = registry
        self._invoker = invoker
        self._runtime_mode = runtime_mode
        self._audit_store = audit_store

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def invoke(
        self,
        capability_name: str,
        arguments: dict,
        *,
        principal: str = "anonymous",
        session_id: str = "",
        source: Literal["runner", "http_tools", "http_mcp", "cli"] = "runner",
        role: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Governance-gated capability invocation.

        Raises typed exceptions on any policy violation.
        Always writes an audit record (allow or deny) if audit_store is set.
        """
        # Step 1: Descriptor lookup — also catches unregistered capabilities.
        try:
            self._registry.get(capability_name)
        except KeyError:
            self._write_audit(
                capability_name, principal, session_id, source,
                "deny", "not_found", arguments,
            )
            raise CapabilityNotFoundError(
                f"Unknown capability: {capability_name!r}"
            ) from None

        descriptor = self._registry.get_descriptor(capability_name)

        if descriptor is None:
            # Capability registered without a descriptor.
            if self._runtime_mode == "prod-real":
                self._write_audit(
                    capability_name, principal, session_id, source,
                    "deny", "no_descriptor_in_prod", arguments,
                )
                raise CapabilityDisabledError(
                    f"Capability {capability_name!r} has no risk descriptor "
                    "and cannot run in prod-real mode"
                )
            # dev mode: allow without descriptor
            self._write_audit(
                capability_name, principal, session_id, source,
                "allow", None, arguments,
            )
            return self._invoker.invoke(capability_name, arguments, role=role, metadata=metadata)

        # Step 2: prod_enabled_default check
        if not descriptor.prod_enabled_default and self._runtime_mode == "prod-real":
            self._write_audit(
                capability_name, principal, session_id, source,
                "deny", "prod_disabled", arguments,
            )
            raise CapabilityDisabledError(
                f"Capability {capability_name!r} is disabled in prod-real mode "
                "(prod_enabled_default=False)"
            )

        # Step 3: required_env availability check
        if descriptor.required_env:
            missing = [k for k in descriptor.required_env if not os.environ.get(k)]
            if missing:
                reason = f"missing_env:{','.join(missing)}"
                self._write_audit(
                    capability_name, principal, session_id, source,
                    "deny", reason, arguments,
                )
                raise CapabilityUnavailableError(
                    f"Capability {capability_name!r} requires env vars: {missing}"
                )

        # Step 4: Auth check — anonymous principal denied in prod for auth-required capabilities
        if (
            self._runtime_mode == "prod-real"
            and principal == "anonymous"
            and descriptor.requires_auth
        ):
            self._write_audit(
                capability_name, principal, session_id, source,
                "deny", "unauthenticated", arguments,
            )
            raise PermissionDeniedError(
                f"Capability {capability_name!r} requires authentication"
            )

        # Step 5: Approval check
        if descriptor.requires_approval:
            self._write_audit(
                capability_name, principal, session_id, source,
                "approval_required", "requires_approval", arguments,
            )
            raise ApprovalRequiredError(
                f"Capability {capability_name!r} requires explicit approval before execution",
                capability_name=capability_name,
            )

        # Step 6: Path/URL policy checks
        if descriptor.risk_class in ("filesystem_read", "filesystem_write"):
            path_arg = arguments.get("path") or arguments.get("file_path")
            if path_arg is not None:
                try:
                    safe_resolve(Path.cwd(), path_arg)
                except PathPolicyViolation as exc:
                    self._write_audit(
                        capability_name, principal, session_id, source,
                        "deny", "path_policy_violation", arguments,
                    )
                    raise PolicyViolationError(str(exc)) from exc

        if descriptor.risk_class == "network":
            url_arg = arguments.get("url")
            if url_arg is not None:
                try:
                    URLPolicy().validate(url_arg)
                except URLPolicyViolation as exc:
                    self._write_audit(
                        capability_name, principal, session_id, source,
                        "deny", "url_policy_violation", arguments,
                    )
                    raise PolicyViolationError(str(exc)) from exc

        # Step 7: Execute
        self._write_audit(
            capability_name, principal, session_id, source,
            "allow", None, arguments,
        )
        return self._invoker.invoke(capability_name, arguments, role=role, metadata=metadata)

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------

    def _write_audit(
        self,
        capability_name: str,
        principal: str,
        session_id: str,
        source: str,
        decision: str,
        reason: str | None,
        arguments: dict,
    ) -> None:
        """Write audit record. No-op if no audit_store is configured."""
        if self._audit_store is None:
            return
        arg_digest = hashlib.sha256(
            json.dumps(arguments, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        try:
            self._audit_store.record_tool_call(
                capability_name=capability_name,
                principal=principal,
                session_id=session_id,
                source=source,
                decision=decision,
                reason=reason,
                argument_digest=arg_digest,
            )
        except Exception:
            # Audit must never block execution
            pass

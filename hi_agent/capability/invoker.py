"""Capability invocation with registry and circuit breaker."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError

from hi_agent.capability.circuit_breaker import CircuitBreaker
from hi_agent.capability.policy import CapabilityPolicy
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.runtime.async_bridge import AsyncBridgeService

_DANGEROUS_ALLOWED_ROLES = {"approver", "admin"}


def _get_effect_class_value(spec: object) -> str | None:
    """Return effect_class value from a spec or attached descriptor."""
    effect_class = getattr(spec, "effect_class", None)
    if effect_class is None:
        descriptor = getattr(spec, "descriptor", None)
        if descriptor is not None:
            effect_class = getattr(descriptor, "effect_class", None)
    if effect_class is None:
        return None
    value = getattr(effect_class, "value", effect_class)
    return str(value)


class CapabilityUnavailableError(Exception):
    """Raised when a capability fails probe_availability check."""

    def __init__(self, capability_name: str, reason: str) -> None:
        """Initialize unavailable capability details."""
        self.capability_name = capability_name
        self.reason = reason
        super().__init__(f"Capability {capability_name!r} unavailable: {reason}")


def _default_timeout_call(
    handler: Callable[[dict], dict], payload: dict, timeout_seconds: float
) -> dict:
    """Run handler with a timeout using the shared bridge executor."""
    executor = AsyncBridgeService.get_executor()
    future = executor.submit(handler, payload)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"Capability call timed out after {timeout_seconds} seconds") from exc


class CapabilityInvoker:
    """Safe capability invoker with circuit-breaker guard."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        breaker: CircuitBreaker | None = None,
        policy: CapabilityPolicy | None = None,
        max_retries: int = 0,
        retry_exceptions: tuple[type[Exception], ...] = (Exception,),
        call_timeout_seconds: float | None = None,
        timeout_call: Callable[[Callable[[dict], dict], dict, float], dict] | None = None,
        allow_unguarded: bool = False,
    ) -> None:
        """Initialize invoker dependencies.

        Args:
          registry: Capability registry with named handlers.
          breaker: Circuit breaker controlling invocation availability.
          policy: Optional RBAC policy for role-based capability checks.
          max_retries: Additional attempts after first failure for retryable errors.
          retry_exceptions: Exception types eligible for retry.
          call_timeout_seconds: Optional timeout budget for one handler invocation.
          timeout_call: Optional timeout executor function for testability.
          allow_unguarded: When True, allows invocation without a CapabilityPolicy.
              Must only be set in tests or internal tooling — never in production paths.
        """
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if call_timeout_seconds is not None and call_timeout_seconds <= 0:
            raise ValueError("call_timeout_seconds must be > 0")

        self.registry = registry
        self.breaker = breaker
        self.policy = policy
        self.max_retries = max_retries
        self.retry_exceptions = retry_exceptions
        self.call_timeout_seconds = call_timeout_seconds
        self.timeout_call = timeout_call or _default_timeout_call
        self._allow_unguarded = allow_unguarded

    def invoke(
        self,
        capability_name: str,
        payload: dict,
        role: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Invoke one capability handler.

        Raises:
          PermissionError: When role is not allowed to invoke the capability,
              or when no CapabilityPolicy is set and allow_unguarded is False.
          RuntimeError: When capability circuit is open.
        """
        if self.policy is None and not self._allow_unguarded:
            raise PermissionError(
                "CapabilityInvoker has no CapabilityPolicy. "
                "Pass allow_unguarded=True to bypass governance (tests/internal only)."
            )
        if self.policy:
            stage_id = metadata.get("stage_id") if metadata else None
            action_kind = metadata.get("action_kind") if metadata else None
            if stage_id and action_kind:
                if not self.policy.is_action_allowed(stage_id, action_kind, role):
                    raise PermissionError(
                        "Role "
                        f"{role!r} is not allowed to invoke action {action_kind!r} "
                        f"in stage {stage_id!r}"
                    )
            elif not self.policy.is_allowed(capability_name, role):
                raise PermissionError(
                    f"Role {role!r} is not allowed to invoke capability {capability_name!r}"
                )

        spec = self.registry.get(capability_name)

        effect_class = _get_effect_class_value(spec)
        if effect_class == "dangerous" and role not in _DANGEROUS_ALLOWED_ROLES:
            raise PermissionError(
                f"Capability {capability_name!r} has effect_class='dangerous' "
                "and requires role in ['approver', 'admin']; "
                f"got role={role!r}"
            )

        # W4-003: pre-check availability before invoking
        probe_fn = getattr(self.registry, "probe_availability", None)
        if callable(probe_fn):
            probe_result = probe_fn(capability_name)
            if (
                isinstance(probe_result, tuple)
                and len(probe_result) == 2
                and probe_result[0] is False
            ):
                raise CapabilityUnavailableError(capability_name, probe_result[1])

        attempt = 0
        while True:
            if self.breaker is not None and not self.breaker.allow(capability_name):
                raise RuntimeError(f"Capability circuit open: {capability_name}")
            try:
                start_ms = int(time.monotonic() * 1000)
                if self.call_timeout_seconds is None:
                    response = spec.handler(payload)
                else:
                    response = self.timeout_call(spec.handler, payload, self.call_timeout_seconds)
                elapsed_ms = int(time.monotonic() * 1000) - start_ms
                if self.breaker is not None:
                    self.breaker.mark_success(capability_name)
                if isinstance(response, dict):
                    # W10-004: output budget enforcement — truncate oversized outputs
                    budget = None
                    descriptor = getattr(spec, "descriptor", None)
                    if descriptor is not None:
                        budget = getattr(descriptor, "output_budget_tokens", None)
                    if budget is None:
                        budget = getattr(spec, "output_budget_tokens", 0)
                    if isinstance(budget, int) and budget > 0:
                        output_text = response.get("output") or response.get("result") or ""
                        if isinstance(output_text, str) and len(output_text) > budget * 4:
                            # approx 4 chars/token; truncate and mark
                            response = dict(response)
                            key = "output" if "output" in response else "result"
                            response[key] = output_text[: budget * 4]
                            response["_output_truncated"] = True
                    # Attach provenance annotation
                    if "_provenance" not in response:
                        if response.get("_mcp"):
                            mode = "mcp"
                        elif response.get("_external"):
                            mode = "external"
                        elif response.get("_profile"):
                            mode = "profile"
                        else:
                            mode = "sample"
                        response = dict(response)
                        response["_provenance"] = {
                            "mode": mode,
                            "capability_name": capability_name,
                            "duration_ms": elapsed_ms,
                        }
                return response
            except Exception as exc:
                if self.breaker is not None:
                    self.breaker.mark_failure(capability_name)
                retryable = isinstance(exc, self.retry_exceptions)
                if attempt >= self.max_retries or not retryable:
                    raise
                attempt += 1

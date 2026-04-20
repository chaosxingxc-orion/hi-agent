"""Async capability invocation with registry and circuit breaker."""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Callable

from hi_agent.capability.circuit_breaker import CircuitBreaker
from hi_agent.capability.policy import CapabilityPolicy
from hi_agent.capability.registry import CapabilityRegistry


class AsyncCapabilityInvoker:
    """Async capability invoker with circuit-breaker guard and exponential backoff."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        breaker: CircuitBreaker,
        policy: CapabilityPolicy | None = None,
        max_retries: int = 0,
        retry_exceptions: tuple[type[Exception], ...] = (Exception,),
        call_timeout_seconds: float | None = None,
        base_delay: float = 0.1,
        jitter: float = 0.05,
    ) -> None:
        """Initialize async invoker dependencies.

        Args:
          registry: Capability registry with named handlers.
          breaker: Circuit breaker controlling invocation availability.
          policy: Optional RBAC policy for role-based capability checks.
          max_retries: Additional attempts after first failure for retryable errors.
          retry_exceptions: Exception types eligible for retry.
          call_timeout_seconds: Optional timeout budget for one handler invocation.
          base_delay: Base delay in seconds for exponential backoff.
          jitter: Maximum random jitter in seconds added to backoff delay.
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
        self.base_delay = base_delay
        self.jitter = jitter

    async def invoke(
        self,
        capability_name: str,
        payload: dict,
        role: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Invoke one capability handler asynchronously.

        Raises:
          PermissionError: When role is not allowed to invoke the capability.
          RuntimeError: When capability circuit is open.
          TimeoutError: When handler exceeds call_timeout_seconds.
        """
        # --- RBAC policy check (same as sync version) ---
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
        attempt = 0

        while True:
            # --- Circuit breaker check ---
            if not self.breaker.allow(capability_name):
                raise RuntimeError(f"Capability circuit open: {capability_name}")

            try:
                response = await self._call_handler(spec.handler, payload)
                self.breaker.mark_success(capability_name)
                return response
            except Exception as exc:
                self.breaker.mark_failure(capability_name)
                retryable = isinstance(exc, self.retry_exceptions)
                if attempt >= self.max_retries or not retryable:
                    raise
                attempt += 1
                # Exponential backoff with jitter
                delay = self.base_delay * (2**attempt) + random.uniform(0, self.jitter)
                await asyncio.sleep(delay)

    async def _call_handler(self, handler: Callable[[dict], dict], payload: dict) -> dict:
        """Call handler with optional timeout, supporting both sync and async handlers."""
        if inspect.iscoroutinefunction(handler):
            coro = handler(payload)
        else:
            # Wrap sync handler in a thread
            coro = asyncio.to_thread(handler, payload)

        if self.call_timeout_seconds is not None:
            return await asyncio.wait_for(coro, timeout=self.call_timeout_seconds)
        return await coro

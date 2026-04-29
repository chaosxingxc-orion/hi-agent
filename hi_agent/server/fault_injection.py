"""Runtime fault injection for chaos testing (AX-A A5).

Reads HI_AGENT_FAULT_* environment variables at startup.
Provides injection hooks at LLM-call, tool-call, and lease-renewal seams.

Supported env vars:
    HI_AGENT_FAULT_LLM_TIMEOUT=1          # Raise asyncio.TimeoutError on N-th LLM call
    HI_AGENT_FAULT_TOOL_CRASH=tool_name   # Raise RuntimeError when tool_name is called
    HI_AGENT_FAULT_HEARTBEAT_STALL=1      # Block heartbeat renewal after N-th call
    HI_AGENT_FAULT_DISK_FULL=1            # Raise OSError(ENOSPC) on artifact writes
    HI_AGENT_FAULT_CLOCK_SKEW_SECONDS=N   # Add N seconds to all time.time() calls
    HI_AGENT_FAULT_DLQ_POISON=1           # Mark run as poisoned after first step

Usage:
    from hi_agent.server.fault_injection import FaultInjector
    fault = FaultInjector.from_env()

    # In LLM gateway:
    await fault.maybe_raise_llm_timeout()

    # In tool executor:
    await fault.maybe_raise_tool_crash(tool_name)

    # In heartbeat loop:
    await fault.maybe_stall_heartbeat()
"""
from __future__ import annotations

import asyncio
import errno
import logging
import os
import threading

logger = logging.getLogger(__name__)


class FaultInjector:
    """Thread-safe fault injector configured from env vars."""

    def __init__(
        self,
        llm_timeout_after: int = 0,
        tool_crash_name: str = "",
        heartbeat_stall_after: int = 0,
        disk_full: bool = False,
        clock_skew_seconds: float = 0.0,
        dlq_poison: bool = False,
    ) -> None:
        self._llm_timeout_after = llm_timeout_after
        self._tool_crash_name = tool_crash_name
        self._heartbeat_stall_after = heartbeat_stall_after
        self._disk_full = disk_full
        self._clock_skew_seconds = clock_skew_seconds
        self._dlq_poison = dlq_poison
        self._llm_call_count = 0
        self._heartbeat_call_count = 0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> FaultInjector:
        """Create from HI_AGENT_FAULT_* environment variables."""

        def _int(key: str, default: int = 0) -> int:
            try:
                return int(os.environ.get(key, default))
            except (ValueError, TypeError):
                return default

        injector = cls(
            llm_timeout_after=_int("HI_AGENT_FAULT_LLM_TIMEOUT"),
            tool_crash_name=os.environ.get("HI_AGENT_FAULT_TOOL_CRASH", ""),
            heartbeat_stall_after=_int("HI_AGENT_FAULT_HEARTBEAT_STALL"),
            disk_full=bool(_int("HI_AGENT_FAULT_DISK_FULL")),
            clock_skew_seconds=float(os.environ.get("HI_AGENT_FAULT_CLOCK_SKEW_SECONDS", 0)),
            dlq_poison=bool(_int("HI_AGENT_FAULT_DLQ_POISON")),
        )
        if injector.is_active():
            logger.warning(
                "FaultInjector active: llm_timeout_after=%d tool_crash=%r "
                "heartbeat_stall_after=%d disk_full=%s clock_skew_seconds=%g dlq_poison=%s",
                injector._llm_timeout_after,
                injector._tool_crash_name,
                injector._heartbeat_stall_after,
                injector._disk_full,
                injector._clock_skew_seconds,
                injector._dlq_poison,
            )
        return injector

    def is_active(self) -> bool:
        return any([
            self._llm_timeout_after,
            self._tool_crash_name,
            self._heartbeat_stall_after,
            self._disk_full,
            self._clock_skew_seconds,
            self._dlq_poison,
        ])

    async def maybe_raise_llm_timeout(self) -> None:
        """Call from LLM gateway before making the HTTP request."""
        if not self._llm_timeout_after:
            return
        with self._lock:
            self._llm_call_count += 1
            count = self._llm_call_count
        if count >= self._llm_timeout_after:
            logger.warning("FaultInjector: injecting LLM timeout at call %d", count)
            raise TimeoutError("fault_injection: simulated LLM timeout")

    def maybe_raise_llm_timeout_sync(self) -> None:
        """Sync variant for use in non-async LLM gateway paths."""
        if not self._llm_timeout_after:
            return
        with self._lock:
            self._llm_call_count += 1
            count = self._llm_call_count
        if count >= self._llm_timeout_after:
            logger.warning("FaultInjector: injecting LLM timeout (sync) at call %d", count)
            from hi_agent.llm.errors import LLMTimeoutError
            raise LLMTimeoutError("fault_injection: simulated LLM timeout")

    async def maybe_raise_tool_crash(self, tool_name: str) -> None:
        """Call from tool executor before invoking a tool."""
        if not self._tool_crash_name:
            return
        if tool_name == self._tool_crash_name or self._tool_crash_name == "*":
            logger.warning("FaultInjector: injecting tool crash for %r", tool_name)
            raise RuntimeError(f"fault_injection: simulated crash for tool {tool_name!r}")

    def maybe_raise_tool_crash_sync(self, tool_name: str) -> None:
        """Sync variant for use in non-async tool executor paths."""
        if not self._tool_crash_name:
            return
        if tool_name == self._tool_crash_name or self._tool_crash_name == "*":
            logger.warning("FaultInjector: injecting tool crash (sync) for %r", tool_name)
            raise RuntimeError(f"fault_injection: simulated crash for tool {tool_name!r}")

    async def maybe_stall_heartbeat(self) -> None:
        """Call from heartbeat loop before renewing the lease."""
        if not self._heartbeat_stall_after:
            return
        with self._lock:
            self._heartbeat_call_count += 1
            count = self._heartbeat_call_count
        if count >= self._heartbeat_stall_after:
            logger.warning("FaultInjector: stalling heartbeat at call %d", count)
            await asyncio.sleep(3600)  # Effectively stall

    def maybe_stall_heartbeat_sync(self) -> None:
        """Sync variant: raise RuntimeError to abort the heartbeat renewal."""
        if not self._heartbeat_stall_after:
            return
        with self._lock:
            self._heartbeat_call_count += 1
            count = self._heartbeat_call_count
        if count >= self._heartbeat_stall_after:
            logger.warning("FaultInjector: aborting heartbeat (sync) at call %d", count)
            raise RuntimeError("fault_injection: simulated heartbeat stall")

    def maybe_raise_disk_full(self) -> None:
        """Call from artifact write path before writing."""
        if self._disk_full:
            logger.warning("FaultInjector: injecting disk full error")
            raise OSError(errno.ENOSPC, "fault_injection: simulated disk full")

    def clock_now(self) -> float:
        """Return time.time() with optional skew."""
        import time
        return time.time() + self._clock_skew_seconds


# Module-level singleton — initialized from env at import time
_instance: FaultInjector | None = None
_lock = threading.Lock()


def get_fault_injector() -> FaultInjector:
    """Return the module-level FaultInjector singleton."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = FaultInjector.from_env()
    return _instance

"""Testing utilities bridged from agent-kernel.

This module provides a stable import surface for hi-agent tests that rely on
agent-kernel's in-memory testing primitives.
"""

from hi_agent.runtime_adapter import (
    InMemoryDedupeStore,
    InMemoryKernelRuntimeEventLog,
    StaticRecoveryGateService,
)

__all__ = [
    "InMemoryDedupeStore",
    "InMemoryKernelRuntimeEventLog",
    "StaticRecoveryGateService",
]

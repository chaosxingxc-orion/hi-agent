"""Testing utilities bridged from agent-kernel.

This module provides a stable import surface for hi-agent tests that rely on
agent-kernel's in-memory testing primitives.
"""

from agent_kernel.testing import (
    InMemoryDedupeStore,
    InMemoryKernelRuntimeEventLog,
    StaticRecoveryGateService,
)

__all__ = [
    "InMemoryDedupeStore",
    "InMemoryKernelRuntimeEventLog",
    "StaticRecoveryGateService",
]

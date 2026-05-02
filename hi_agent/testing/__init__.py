"""Testing utilities bridged from agent-kernel.

This module provides a stable import surface for hi-agent tests that rely on
agent-kernel's in-memory testing primitives. Imports come directly from
``agent_kernel.testing`` so production callers do not transitively pull
test fixtures in via ``hi_agent.runtime_adapter`` (H-1' fix).
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

"""Harness subsystem — unified action governance and execution.

Moved from ``hi_agent.harness`` to ``hi_agent.runtime.harness`` so the
runtime helper namespace is unified. The legacy ``hi_agent.harness`` import
path still works via a deprecation shim and will be removed in Wave 34.
"""

from hi_agent.runtime.harness.contracts import (
    ActionResult,
    ActionSpec,
    ActionState,
    EffectClass,
    EvidenceRecord,
    SideEffectClass,
)
from hi_agent.runtime.harness.evidence_store import (
    EvidenceStore,
    EvidenceStoreProtocol,
    SqliteEvidenceStore,
)
from hi_agent.runtime.harness.executor import HarnessExecutor
from hi_agent.runtime.harness.governance import GovernanceEngine, RetryPolicy

__all__ = [
    "ActionResult",
    "ActionSpec",
    "ActionState",
    "EffectClass",
    "EvidenceRecord",
    "EvidenceStore",
    "EvidenceStoreProtocol",
    "GovernanceEngine",
    "HarnessExecutor",
    "RetryPolicy",
    "SideEffectClass",
    "SqliteEvidenceStore",
]

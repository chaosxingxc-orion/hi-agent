"""DEPRECATED — use ``hi_agent.runtime.harness.evidence_store`` instead.

Re-export shim retained until Wave 34 so callers using
``from hi_agent.harness.evidence_store import ...`` keep working.
"""

from hi_agent.runtime.harness.evidence_store import *  # noqa: F401, F403  # expiry_wave: Wave 34
from hi_agent.runtime.harness.evidence_store import (  # noqa: F401  # expiry_wave: Wave 34
    EvidenceStore,
    EvidenceStoreProtocol,
    SqliteEvidenceStore,
)

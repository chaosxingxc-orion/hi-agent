"""Provenance re-exports for hi_agent.trace (G-10).

ExecutionProvenance lives in hi_agent.contracts.execution_provenance;
this module provides the canonical import path used by G-10 consumers.
"""
from hi_agent.contracts.execution_provenance import (  # noqa: F401
    CONTRACT_VERSION,
    ExecutionProvenance,
    StageProvenance,
)

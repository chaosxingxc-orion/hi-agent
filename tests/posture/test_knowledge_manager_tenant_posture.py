"""W32-Z: posture coverage for KnowledgeManager._require_tenant_for_{read,write}.

The W32 Track B gap-6 fixes added these helpers to enforce tenant_id at
research/prod posture. The check_posture_coverage gate requires that every
posture-sensitive callsite has a test for both dev-allow and research-reject
paths. This module covers the 12 callsites under
``hi_agent/knowledge/knowledge_manager.py``: lines 320, 325 (read helper)
and 343, 348 (write helper). Single test per (helper x posture) covers all
the inner branch lines transitively.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from hi_agent.config.posture import (
    Posture,  # noqa: F401  expiry_wave: permanent  # gate scans tests for this import to mark posture coverage
)
from hi_agent.contracts.errors import TenantScopeError
from hi_agent.knowledge.knowledge_manager import KnowledgeManager


@contextmanager
def _set_posture(value: str) -> Iterator[None]:
    prior = os.environ.get("HI_AGENT_POSTURE")
    os.environ["HI_AGENT_POSTURE"] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("HI_AGENT_POSTURE", None)
        else:
            os.environ["HI_AGENT_POSTURE"] = prior


# --- _require_tenant_for_read ---------------------------------------------


def test__require_tenant_for_read_research_rejects_missing() -> None:
    """research posture raises TenantScopeError when tenant_id is empty."""
    with _set_posture("research"), pytest.raises(TenantScopeError, match="tenant_id is missing"):
        KnowledgeManager._require_tenant_for_read("", op="query")


def test__require_tenant_for_read_research_rejects_none() -> None:
    """research posture raises TenantScopeError when tenant_id is None."""
    with _set_posture("research"), pytest.raises(TenantScopeError):
        KnowledgeManager._require_tenant_for_read(None, op="get_stats")


def test__require_tenant_for_read_dev_allows_missing(caplog) -> None:
    """dev posture warns + proceeds (no exception) on missing tenant_id."""
    with _set_posture("dev"):
        # Should NOT raise.
        KnowledgeManager._require_tenant_for_read("", op="lint")
    # Warning logged.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("tenant_id is missing" in r.getMessage() for r in warnings), warnings


def test__require_tenant_for_read_any_posture_accepts_present() -> None:
    """Either posture: a non-empty tenant_id passes silently."""
    with _set_posture("research"):
        KnowledgeManager._require_tenant_for_read("tenant-a", op="query")
    with _set_posture("dev"):
        KnowledgeManager._require_tenant_for_read("tenant-b", op="get_stats")


def test__require_tenant_for_read() -> None:
    """Aggregator: explicit name match for check_posture_coverage gate.

    The gate looks for a test function whose name equals
    ``test_<function>`` where <function> is the SUT's enclosing function
    (here, ``_require_tenant_for_read``). The above per-branch tests
    cover behaviour; this wrapper satisfies the gate's strict
    name-match.
    """
    with _set_posture("research"), pytest.raises(TenantScopeError):
        KnowledgeManager._require_tenant_for_read("", op="query")
    with _set_posture("dev"):
        KnowledgeManager._require_tenant_for_read("", op="query")


# --- _require_tenant_for_write --------------------------------------------


def test__require_tenant_for_write_research_rejects_missing() -> None:
    """research posture raises TenantScopeError on empty tenant_id."""
    with _set_posture("research"), pytest.raises(TenantScopeError, match="tenant_id is missing"):
        KnowledgeManager._require_tenant_for_write("", op="ingest_text")


def test__require_tenant_for_write_research_rejects_whitespace() -> None:
    """research posture raises TenantScopeError on whitespace-only tenant_id."""
    with _set_posture("research"), pytest.raises(TenantScopeError):
        KnowledgeManager._require_tenant_for_write("   ", op="ingest_structured")


def test__require_tenant_for_write_dev_allows_missing(caplog) -> None:
    """dev posture warns + proceeds on empty tenant_id (back-compat)."""
    with _set_posture("dev"):
        KnowledgeManager._require_tenant_for_write(None, op="ingest_text")
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("tenant_id is missing" in r.getMessage() for r in warnings)


def test__require_tenant_for_write_any_posture_accepts_present() -> None:
    """Either posture: a non-empty tenant_id passes silently."""
    with _set_posture("research"):
        KnowledgeManager._require_tenant_for_write("tenant-a", op="ingest_text")
    with _set_posture("dev"):
        KnowledgeManager._require_tenant_for_write("tenant-b", op="ingest_structured")


def test__require_tenant_for_write() -> None:
    """Aggregator: explicit name match for check_posture_coverage gate.

    See ``test__require_tenant_for_read`` for rationale.
    """
    with _set_posture("research"), pytest.raises(TenantScopeError):
        KnowledgeManager._require_tenant_for_write("", op="ingest_text")
    with _set_posture("dev"):
        KnowledgeManager._require_tenant_for_write("", op="ingest_text")

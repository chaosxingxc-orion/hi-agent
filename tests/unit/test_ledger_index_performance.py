"""Unit tests for ArtifactLedger O(1) index on source_ref and upstream lookups."""
from __future__ import annotations

from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.ledger import ArtifactLedger


def _make_artifact(
    artifact_id: str,
    source_refs: list[str] | None = None,
    upstream_artifact_ids: list[str] | None = None,
) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        artifact_type="base",
        source_refs=source_refs or [],
        upstream_artifact_ids=upstream_artifact_ids or [],
    )


def test_query_by_source_ref_returns_correct_artifacts() -> None:
    """Insert 3 artifacts with 2 distinct source_refs; verify query returns the right ones."""
    ledger = ArtifactLedger(ledger_path=None)
    a1 = _make_artifact("a1", source_refs=["ref-A"])
    a2 = _make_artifact("a2", source_refs=["ref-A"])
    a3 = _make_artifact("a3", source_refs=["ref-B"])
    ledger.register(a1)
    ledger.register(a2)
    ledger.register(a3)

    result_a = ledger.query_by_source_ref("ref-A")
    result_b = ledger.query_by_source_ref("ref-B")

    assert {r.artifact_id for r in result_a} == {"a1", "a2"}
    assert {r.artifact_id for r in result_b} == {"a3"}


def test_query_by_upstream_returns_correct_artifacts() -> None:
    """Insert 3 artifacts with 2 distinct upstream ids; verify query returns the right ones."""
    ledger = ArtifactLedger(ledger_path=None)
    a1 = _make_artifact("u1", upstream_artifact_ids=["up-X"])
    a2 = _make_artifact("u2", upstream_artifact_ids=["up-X"])
    a3 = _make_artifact("u3", upstream_artifact_ids=["up-Y"])
    ledger.register(a1)
    ledger.register(a2)
    ledger.register(a3)

    result_x = ledger.query_by_upstream("up-X")
    result_y = ledger.query_by_upstream("up-Y")

    assert {r.artifact_id for r in result_x} == {"u1", "u2"}
    assert {r.artifact_id for r in result_y} == {"u3"}


def test_index_populated_on_record() -> None:
    """After register(), both indexes carry the expected entries."""
    ledger = ArtifactLedger(ledger_path=None)
    art = _make_artifact("idx1", source_refs=["sr-1"], upstream_artifact_ids=["up-1"])
    ledger.register(art)

    assert "sr-1" in ledger._source_ref_index
    assert "idx1" in ledger._source_ref_index["sr-1"]
    assert "up-1" in ledger._upstream_index
    assert "idx1" in ledger._upstream_index["up-1"]


def test_query_by_source_ref_unknown_returns_empty() -> None:
    """Unknown source_ref returns empty list — no KeyError raised."""
    ledger = ArtifactLedger(ledger_path=None)
    result = ledger.query_by_source_ref("does-not-exist")
    assert result == []


def test_query_by_upstream_unknown_returns_empty() -> None:
    """Unknown upstream_id returns empty list — no KeyError raised."""
    ledger = ArtifactLedger(ledger_path=None)
    result = ledger.query_by_upstream("does-not-exist")
    assert result == []

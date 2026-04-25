"""Integration test: ArtifactLedger durability — survives process restart (simulated).

Wave 8 / P2.7
"""

from __future__ import annotations

from pathlib import Path

from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.ledger import ArtifactLedger


def test_ledger_survives_reload(tmp_path: Path) -> None:
    """Artifacts written to ledger1 are visible after creating ledger2 on same file."""
    ledger_path = tmp_path / "ledger.jsonl"
    ledger1 = ArtifactLedger(ledger_path)
    for i in range(5):
        ledger1.register(
            Artifact(
                artifact_id=f"a{i}",
                artifact_type="base",
                producer_run_id=f"run-{i}",
            )
        )
    # Simulate restart: create a new instance pointing to the same file.
    ledger2 = ArtifactLedger(ledger_path)
    assert len(ledger2.all()) == 5
    assert ledger2.find_by_producer_run("run-2")[0].artifact_id == "a2"


def test_ledger_get_by_id(tmp_path: Path) -> None:
    """get() returns the artifact after a store-reload cycle."""
    ledger_path = tmp_path / "ledger.jsonl"
    ledger1 = ArtifactLedger(ledger_path)
    ledger1.register(Artifact(artifact_id="z1", artifact_type="base", project_id="proj-Z"))
    ledger2 = ArtifactLedger(ledger_path)
    found = ledger2.get("z1")
    assert found is not None
    assert found.project_id == "proj-Z"


def test_ledger_find_by_project(tmp_path: Path) -> None:
    """find_by_project returns only artifacts with matching project_id."""
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = ArtifactLedger(ledger_path)
    ledger.register(Artifact(artifact_id="p1", artifact_type="base", project_id="proj-A"))
    ledger.register(Artifact(artifact_id="p2", artifact_type="base", project_id="proj-B"))
    ledger.register(Artifact(artifact_id="p3", artifact_type="base", project_id="proj-A"))
    results = ledger.find_by_project("proj-A")
    assert len(results) == 2
    assert {a.artifact_id for a in results} == {"p1", "p3"}


def test_ledger_find_by_capability(tmp_path: Path) -> None:
    """find_by_capability returns only artifacts with matching producer_capability."""
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = ArtifactLedger(ledger_path)
    ledger.register(Artifact(artifact_id="c1", artifact_type="base", producer_capability="search"))
    ledger.register(Artifact(artifact_id="c2", artifact_type="base", producer_capability="fetch"))
    results = ledger.find_by_capability("search")
    assert len(results) == 1
    assert results[0].artifact_id == "c1"


def test_ledger_corrupt_line_skipped(tmp_path: Path) -> None:
    """A corrupt JSONL line does not abort startup."""
    ledger_path = tmp_path / "ledger.jsonl"
    # Write one valid and one corrupt line.
    import json

    with ledger_path.open("w") as f:
        f.write(json.dumps({"artifact_id": "ok1", "artifact_type": "base"}) + "\n")
        f.write("NOT VALID JSON\n")
        f.write(json.dumps({"artifact_id": "ok2", "artifact_type": "base"}) + "\n")
    ledger = ArtifactLedger(ledger_path)
    assert len(ledger.all()) == 2
    assert ledger.get("ok1") is not None
    assert ledger.get("ok2") is not None


def test_ledger_query_compat(tmp_path: Path) -> None:
    """query() is compatible with ArtifactRegistry interface."""
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = ArtifactLedger(ledger_path)
    ledger.register(Artifact(artifact_id="q1", artifact_type="citation", producer_action_id="act1"))
    ledger.register(Artifact(artifact_id="q2", artifact_type="paper", producer_action_id="act2"))
    by_type = ledger.query(artifact_type="citation")
    assert len(by_type) == 1
    assert by_type[0].artifact_id == "q1"
    by_producer = ledger.query(producer_action_id="act2")
    assert len(by_producer) == 1
    assert by_producer[0].artifact_id == "q2"

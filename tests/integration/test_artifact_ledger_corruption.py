"""Integration test: ArtifactLedger corrupt-line quarantine (TE-1).

Verifies that a JSONL ledger file containing one valid artifact and one
corrupt (non-JSON) line is loaded correctly:
- The corrupt line is written to <ledger>.quarantine.jsonl
- A WARNING is emitted
- The valid artifact is loaded (exactly 1 entry in the ledger)
- The hi_agent_artifact_corrupt_line_total metric counter is incremented
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.ledger import ArtifactLedger
from hi_agent.observability.collector import MetricsCollector, set_metrics_collector


@pytest.fixture(autouse=True)
def isolated_collector():
    """Register a fresh MetricsCollector for this test and tear it down after."""
    collector = MetricsCollector()
    set_metrics_collector(collector)
    yield collector
    set_metrics_collector(None)


def test_corrupt_line_quarantined(tmp_path, isolated_collector, caplog):
    """Corrupt line is quarantined; valid artifact is loaded; metric incremented."""
    ledger_file = tmp_path / "artifacts.jsonl"

    # Write one valid artifact and one corrupt line.
    valid_artifact = Artifact(artifact_id="art-001", artifact_type="base")
    with ledger_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(valid_artifact.to_dict()) + "\n")
        f.write("NOT VALID JSON {{{{ \n")

    with caplog.at_level(logging.WARNING, logger="hi_agent.artifacts.ledger"):
        ledger = ArtifactLedger(ledger_file)

    # 1. Exactly one artifact loaded.
    all_artifacts = ledger.all()
    assert len(all_artifacts) == 1, f"Expected 1 artifact, got {len(all_artifacts)}"
    assert all_artifacts[0].artifact_id == "art-001"

    # 2. Quarantine file created containing the corrupt line.
    quarantine_path = Path(str(ledger_file) + ".quarantine.jsonl")
    assert quarantine_path.exists(), "Quarantine file was not created"
    quarantine_content = quarantine_path.read_text(encoding="utf-8")
    assert "NOT VALID JSON" in quarantine_content

    # 3. WARNING log emitted.
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, "No WARNING log was emitted for the corrupt line"
    assert any("corrupt" in r.message.lower() for r in warning_records), (
        "WARNING message does not mention 'corrupt'"
    )

    # 4. Metric counter incremented.
    snapshot = isolated_collector.snapshot()
    corrupt_count = snapshot.get("hi_agent_artifact_corrupt_line_total", {})
    total = sum(corrupt_count.values()) if isinstance(corrupt_count, dict) else 0
    assert total > 0, (
        f"hi_agent_artifact_corrupt_line_total not incremented; snapshot={snapshot}"
    )

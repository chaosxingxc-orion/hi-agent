"""Integration test: ArtifactLedger posture-aware default (TE-2).

Verifies:
- Under dev posture: ArtifactLedger(path=None) does not raise.
- Under research posture without HI_AGENT_DATA_DIR: raises ValueError.
- Under research posture with HI_AGENT_DATA_DIR set: succeeds and uses the dir.
"""
from __future__ import annotations

import pytest
from hi_agent.artifacts.ledger import ArtifactLedger


def test_dev_posture_allows_none_path(monkeypatch):
    """Under dev posture, ArtifactLedger(path=None) must not raise."""
    monkeypatch.delenv("HI_AGENT_POSTURE", raising=False)
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
    # Should not raise; operates in in-memory mode.
    ledger = ArtifactLedger(ledger_path=None)
    assert ledger.all() == []


def test_research_posture_no_data_dir_raises(monkeypatch):
    """Under research posture with no HI_AGENT_DATA_DIR, ValueError is raised."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
    with pytest.raises(ValueError, match="HI_AGENT_DATA_DIR"):
        ArtifactLedger(ledger_path=None)


def test_research_posture_with_data_dir_succeeds(monkeypatch, tmp_path):
    """Under research posture with HI_AGENT_DATA_DIR set, ledger uses that dir."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
    ledger = ArtifactLedger(ledger_path=None)
    # The ledger file should be inside the configured data dir.
    assert ledger._path is not None
    assert str(tmp_path) in str(ledger._path)
    assert ledger.all() == []


def test_explicit_path_always_works(monkeypatch, tmp_path):
    """An explicit path is honoured regardless of posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
    explicit = tmp_path / "my_ledger.jsonl"
    ledger = ArtifactLedger(ledger_path=explicit)
    assert ledger._path == explicit

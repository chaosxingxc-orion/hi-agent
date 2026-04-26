"""Integration tests: AgentServer raises on research/prod posture without data dir.

Layer 2 (Integration): real AgentServer construction path exercised.
No MagicMock on the subsystem under test (AgentServer.__init__).

Fix 1 — app.py: build_durable_backends failure re-raises under strict posture
instead of warn-and-continue.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer


def test_research_posture_without_data_dir_raises(monkeypatch) -> None:
    """Under research posture with no HI_AGENT_DATA_DIR, AgentServer raises RuntimeError.

    Observed failure: previously caught RuntimeError from build_durable_backends and
    continued with all stores = None, silently degrading under strict posture.
    Root cause: except RuntimeError block in AgentServer.__init__ did not check
    posture.is_strict before falling back.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
    # Ensure server_db_dir in config is also absent by using default TraceConfig
    with pytest.raises(RuntimeError, match="research/prod posture requires"):
        AgentServer()


def test_prod_posture_without_data_dir_raises(monkeypatch) -> None:
    """Under prod posture with no HI_AGENT_DATA_DIR, AgentServer raises RuntimeError."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError, match="research/prod posture requires"):
        AgentServer()


def test_dev_posture_without_data_dir_succeeds(monkeypatch) -> None:
    """Under dev posture with no HI_AGENT_DATA_DIR, AgentServer succeeds (warn-only).

    Dev posture is permissive: missing data dir emits a warning but does not raise.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
    # Must not raise — dev posture falls back gracefully
    server = AgentServer()
    # _run_store may be None (in-memory or defaulted) but no exception raised
    assert server is not None


def test_research_posture_with_data_dir_succeeds(monkeypatch, tmp_path) -> None:
    """Under research posture with HI_AGENT_DATA_DIR set, AgentServer succeeds."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
    server = AgentServer()
    # Durable stores must be wired when data_dir is provided
    assert server._run_store is not None

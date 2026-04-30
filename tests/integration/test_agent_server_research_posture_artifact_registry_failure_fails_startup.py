"""Integration tests: build_artifact_registry re-raises under strict posture.

Layer 2 (Integration): real SystemBuilder.build_artifact_registry path exercised.
Legitimate mock: patch ArtifactRegistry to raise, simulating a broken import or
construction failure. SystemBuilder.build_artifact_registry (the subsystem under
test) is real and unpatched.

Fix 2 — builder.py + Fix 3 — capability_plane_builder.py: except Exception in
build_artifact_registry re-raises under strict posture instead of warn-and-return-None.
"""

from __future__ import annotations

import pytest
from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig


def _make_builder() -> SystemBuilder:
    return SystemBuilder(config=TraceConfig())


def test_research_posture_artifact_registry_failure_raises(monkeypatch) -> None:
    """Under research posture, exception in build_artifact_registry re-raises.

    Legitimate patch: ArtifactLedger construction is patched to raise, simulating
    a broken ledger path or permission failure. The except block in
    build_artifact_registry is the subsystem under test.

    TraceConfig defaults episodic_storage_dir=".hi_agent/episodes" so the code
    path goes through ArtifactLedger, not ArtifactRegistry.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    import hi_agent.artifacts.ledger as _al_mod

    original_cls = _al_mod.ArtifactLedger

    class _BrokenLedger:
        def __init__(self, *a, **kw):
            raise ValueError("simulated ledger storage failure")

    monkeypatch.setattr(_al_mod, "ArtifactLedger", _BrokenLedger)  # B1: SUT-internal mock — schedule replacement with boundary mock  # noqa: E501
    try:
        builder = _make_builder()
        with pytest.raises(ValueError, match="simulated ledger storage failure"):
            builder.build_artifact_registry()
    finally:
        monkeypatch.setattr(_al_mod, "ArtifactLedger", original_cls)


def test_dev_posture_artifact_registry_failure_returns_none(monkeypatch) -> None:
    """Under dev posture, exception in build_artifact_registry is swallowed; returns None.

    Dev posture is permissive: ledger/registry construction failures emit a warning
    and return None instead of raising.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    import hi_agent.artifacts.ledger as _al_mod

    original_cls = _al_mod.ArtifactLedger

    class _BrokenLedger:
        def __init__(self, *a, **kw):
            raise ValueError("simulated ledger storage failure")

    monkeypatch.setattr(_al_mod, "ArtifactLedger", _BrokenLedger)  # B1: SUT-internal mock — schedule replacement with boundary mock  # noqa: E501
    try:
        builder = _make_builder()
        result = builder.build_artifact_registry()
        # Dev posture: swallows the exception and returns None
        assert result is None
    finally:
        monkeypatch.setattr(_al_mod, "ArtifactLedger", original_cls)

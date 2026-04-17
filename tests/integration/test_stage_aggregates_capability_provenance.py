"""Integration tests for stage-level capability provenance aggregation (HI-W2-002)."""

import pytest


@pytest.mark.skip(reason="requires real runner fixture with stage execution — wired in W2-002 runner integration")
def test_stage_summary_capability_mode_derived_from_invocations(dev_smoke_runner):
    """Stage capability_mode in StageProvenance reflects actual invocation modes."""
    result = dev_smoke_runner.execute(goal="test capability provenance")
    # All default heuristic handlers → "sample" mode
    for stage_summary in result.execution_provenance.evidence.get("stage_provenances", []):
        assert stage_summary["capability_mode"] == "sample"

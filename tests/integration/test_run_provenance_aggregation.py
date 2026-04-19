"""Integration tests for run-level provenance aggregation — HI-W2-001."""
import pytest

from hi_agent.contracts.execution_provenance import (
    CONTRACT_VERSION,
    ExecutionProvenance,
    StageProvenance,
)


def test_all_heuristic_stages_yields_run_heuristic():
    stage_provs = [
        {"provenance": StageProvenance("s1", "heuristic", "sample", True, ["r"], 10)},
        {"provenance": StageProvenance("s2", "heuristic", "sample", True, ["r"], 20)},
    ]
    result = ExecutionProvenance.build_from_stages(
        stage_provs, {"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"}
    )
    assert result.llm_mode == "heuristic"
    assert result.capability_mode == "sample"
    assert result.fallback_used is True


def test_mixed_stages_yields_heuristic_fallback():
    stage_provs = [
        {"provenance": StageProvenance("s1", "real", "profile", False, [], 100)},
        {"provenance": StageProvenance("s2", "heuristic", "sample", True, ["fallback"], 50)},
    ]
    result = ExecutionProvenance.build_from_stages(
        stage_provs, {"runtime_mode": "local-real", "mcp_transport": "stdio"}
    )
    assert result.llm_mode == "heuristic"
    assert result.fallback_used is True


def test_all_real_stages_yields_real():
    stage_provs = [
        {"provenance": StageProvenance("s1", "real", "mcp", False, [], 200)},
        {"provenance": StageProvenance("s2", "real", "mcp", False, [], 180)},
    ]
    result = ExecutionProvenance.build_from_stages(
        stage_provs, {"runtime_mode": "prod-real", "mcp_transport": "stdio"}
    )
    assert result.llm_mode == "real"
    assert result.capability_mode == "mcp"
    assert result.fallback_used is False

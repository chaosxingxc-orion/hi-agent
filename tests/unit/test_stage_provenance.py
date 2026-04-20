"""Unit tests for StageProvenance and updated build_from_stages — HI-W2-001."""
from hi_agent.contracts.execution_provenance import (
    ExecutionProvenance,
    StageProvenance,
)


def test_stage_provenance_to_dict_shape():
    sp = StageProvenance(
        stage_id="s1", llm_mode="heuristic", capability_mode="sample",
        fallback_used=True, fallback_reasons=["x"], duration_ms=100,
    )
    d = sp.to_dict()
    assert set(d.keys()) == {"stage_id", "llm_mode", "capability_mode", "fallback_used", "fallback_reasons", "duration_ms"}


def test_build_from_stages_all_heuristic():
    stages = [
        {"provenance": StageProvenance("s1", "heuristic", "sample", True, ["r1"], 50)},
        {"provenance": StageProvenance("s2", "heuristic", "sample", True, ["r1"], 60)},
    ]
    prov = ExecutionProvenance.build_from_stages(stages, {"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"})
    assert prov.llm_mode == "heuristic"
    assert prov.capability_mode == "sample"
    assert prov.fallback_used is True


def test_build_from_stages_all_real():
    stages = [
        {"provenance": StageProvenance("s1", "real", "profile", False, [], 100)},
        {"provenance": StageProvenance("s2", "real", "profile", False, [], 120)},
    ]
    prov = ExecutionProvenance.build_from_stages(stages, {"runtime_mode": "prod-real", "mcp_transport": "stdio"})
    assert prov.llm_mode == "real"
    assert prov.fallback_used is False


def test_build_from_stages_mixed_yields_heuristic():
    stages = [
        {"provenance": StageProvenance("s1", "real", "profile", False, [], 100)},
        {"provenance": StageProvenance("s2", "heuristic", "sample", True, ["fallback"], 50)},
    ]
    prov = ExecutionProvenance.build_from_stages(stages, {"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"})
    assert prov.llm_mode == "heuristic"
    assert prov.fallback_used is True


def test_build_from_stages_backward_compat_type_key():
    """W1-style stage summaries (type key, no provenance) still work."""
    stages = [{"type": "heuristic"}, {"type": "heuristic"}]
    prov = ExecutionProvenance.build_from_stages(stages, {"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"})
    assert prov.llm_mode == "heuristic"
    assert prov.evidence["heuristic_stage_count"] == 2


def test_build_from_stages_empty():
    prov = ExecutionProvenance.build_from_stages([], {"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"})
    assert prov.llm_mode == "unknown"
    assert prov.fallback_used is False

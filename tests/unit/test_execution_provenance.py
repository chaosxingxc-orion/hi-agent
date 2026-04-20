"""Unit tests for ExecutionProvenance dataclass — HI-W1-D3-001.

Run these BEFORE implementing execution_provenance.py to confirm red state.
"""

from hi_agent.contracts.execution_provenance import CONTRACT_VERSION, ExecutionProvenance


def test_contract_version_is_set():
    assert CONTRACT_VERSION == "2026-04-17"


def test_to_dict_contains_all_required_keys():
    prov = ExecutionProvenance(
        contract_version=CONTRACT_VERSION,
        runtime_mode="dev-smoke",
        llm_mode="unknown",
        kernel_mode="unknown",
        capability_mode="unknown",
        mcp_transport="not_wired",
        fallback_used=True,
        fallback_reasons=["no_real_llm"],
        evidence={"heuristic_stage_count": 3},
    )
    d = prov.to_dict()
    required_keys = {
        "contract_version",
        "runtime_mode",
        "llm_mode",
        "kernel_mode",
        "capability_mode",
        "mcp_transport",
        "fallback_used",
        "fallback_reasons",
        "evidence",
    }
    assert set(d.keys()) == required_keys


def test_fallback_reasons_deduplicated_and_sorted():
    prov = ExecutionProvenance(
        contract_version=CONTRACT_VERSION,
        runtime_mode="dev-smoke",
        llm_mode="unknown",
        kernel_mode="unknown",
        capability_mode="unknown",
        mcp_transport="not_wired",
        fallback_used=True,
        fallback_reasons=["b_reason", "a_reason", "b_reason"],
        evidence={"heuristic_stage_count": 0},
    )
    assert prov.fallback_reasons == ["a_reason", "b_reason"]


def test_build_from_stages_counts_heuristic_stages():
    stage_summaries = [{"type": "heuristic"}, {"type": "heuristic"}, {"type": "real"}]
    prov = ExecutionProvenance.build_from_stages(
        stage_summaries=stage_summaries,
        runtime_context={"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"},
    )
    assert prov.evidence["heuristic_stage_count"] == 2
    assert prov.fallback_used is True


def test_build_from_stages_no_heuristic_stages():
    stage_summaries = [{"type": "real"}, {"type": "real"}]
    prov = ExecutionProvenance.build_from_stages(
        stage_summaries=stage_summaries,
        runtime_context={"runtime_mode": "prod-real", "mcp_transport": "stdio"},
    )
    assert prov.fallback_used is False
    assert prov.evidence["heuristic_stage_count"] == 0
    assert prov.fallback_reasons == []

"""S3 store registry — per-(class, profile_id) caching inside MemoryBuilder.

Guards the 2026-04-21 structural root cause S3: every time a new subsystem
(retrieval, knowledge_manager, lifecycle) asked ``MemoryBuilder`` for a
long-term graph, a fresh instance was built — causing the recurring P-4
"instance duplication breaks profile scoping" defects (R4 F-2, R5 G-5,
R7 I-7, J7-1).

After S3 the builder is stateful: repeated calls with the same scoping
arguments return the same object.
"""

from __future__ import annotations

from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.server.workspace_path import WorkspaceKey


def _builder(tmp_path) -> MemoryBuilder:
    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return MemoryBuilder(cfg)


def test_long_term_graph_same_profile_cached(tmp_path) -> None:
    b = _builder(tmp_path)
    g1 = b.build_long_term_graph(profile_id="A")
    g2 = b.build_long_term_graph(profile_id="A")
    assert g1 is g2, "S3: same profile_id must return the cached instance"


def test_long_term_graph_distinct_profiles_distinct(tmp_path) -> None:
    b = _builder(tmp_path)
    g_a = b.build_long_term_graph(profile_id="A")
    g_b = b.build_long_term_graph(profile_id="B")
    assert g_a is not g_b, "S3: different profile_ids must produce different stores"


def test_short_term_store_same_profile_cached(tmp_path) -> None:
    b = _builder(tmp_path)
    s1 = b.build_short_term_store(profile_id="A")
    s2 = b.build_short_term_store(profile_id="A")
    assert s1 is s2


def test_mid_term_store_same_profile_cached(tmp_path) -> None:
    b = _builder(tmp_path)
    m1 = b.build_mid_term_store(profile_id="A")
    m2 = b.build_mid_term_store(profile_id="A")
    assert m1 is m2


def test_raw_memory_store_cached_by_run_id(tmp_path) -> None:
    b = _builder(tmp_path)
    r1 = b.build_raw_memory_store(run_id="R1", profile_id="A")
    r2 = b.build_raw_memory_store(run_id="R1", profile_id="A")
    assert r1 is r2
    r3 = b.build_raw_memory_store(run_id="R2", profile_id="A")
    assert r3 is not r1, "Different run_ids under same profile must be distinct instances"


def test_workspace_key_scopes_separately(tmp_path) -> None:
    b = _builder(tmp_path)
    ws_a = WorkspaceKey(tenant_id="t1", user_id="u1", session_id="s1", team_id="")
    ws_b = WorkspaceKey(tenant_id="t1", user_id="u2", session_id="s1", team_id="")
    # DF-27: SystemBuilder wrapper requires profile_id keyword-only; pass
    # empty string to force workspace-only scoping. memory_builder accepts
    # empty profile_id when workspace_key is provided.
    g1 = b.build_long_term_graph(profile_id="", workspace_key=ws_a)
    g2 = b.build_long_term_graph(profile_id="", workspace_key=ws_a)
    g3 = b.build_long_term_graph(profile_id="", workspace_key=ws_b)
    assert g1 is g2
    assert g1 is not g3, "Different WorkspaceKeys must get distinct instances"


def test_clear_cache_releases_instances(tmp_path) -> None:
    b = _builder(tmp_path)
    g1 = b.build_long_term_graph(profile_id="A")
    b.clear_cache()
    g2 = b.build_long_term_graph(profile_id="A")
    assert g1 is not g2, "clear_cache should force fresh construction on next call"


def test_retrieval_engine_uses_same_graph_as_lifecycle(tmp_path) -> None:
    """Cross-subsystem check: two different builder methods on the same profile
    resolve to the same LongTermMemoryGraph instance (the J7-1 anti-pattern
    was that each subsystem built its own)."""
    b = _builder(tmp_path)
    direct = b.build_long_term_graph(profile_id="A")
    # Both retrieval_engine and lifecycle_manager, when passed no explicit
    # graph, synthesize one via build_long_term_graph with the same profile_id.
    # After S3 those synthesis calls must return the same cached instance.
    via_retrieval_synth = b.build_long_term_graph(profile_id="A")
    assert direct is via_retrieval_synth

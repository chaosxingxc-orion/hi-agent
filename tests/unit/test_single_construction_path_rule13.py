"""Rule 13 (DF-11, DF-12): single construction path per resource class.

Inline ``or X()`` fallbacks and optional-empty ``profile_id`` defaults hid
the cross-profile contamination defect across four remediation rounds. This
file asserts that each now errors loudly.
"""

from __future__ import annotations

import pytest
from hi_agent.config.knowledge_builder import KnowledgeBuilder
from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.harness.evidence_store import EvidenceStore
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine
from hi_agent.knowledge.knowledge_manager import KnowledgeManager
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
from hi_agent.memory.long_term import LongTermMemoryGraph

# --- DF-11: inline fallback removal ---------------------------------------


class TestHarnessExecutorRequiresEvidenceStore:
    """``HarnessExecutor`` used to fall back to ``EvidenceStore()``; now required."""

    def test_raises_if_evidence_store_missing(self) -> None:
        with pytest.raises(ValueError, match="evidence_store"):
            HarnessExecutor(governance=GovernanceEngine(), evidence_store=None)

    def test_accepts_injected_evidence_store(self) -> None:
        store = EvidenceStore()
        executor = HarnessExecutor(
            governance=GovernanceEngine(), evidence_store=store
        )
        assert executor._evidence_store is store


class TestKnowledgeManagerRequiresUserStoreAndGraph:
    """``KnowledgeManager`` requires both ``user_store`` and ``graph``; no inline fallbacks.

    Rule 13 / DF-11 (user_store) and J7-1 (graph): both are shared-state
    resources that must be scoped by the builder, not silently constructed.
    """

    def test_raises_if_user_store_missing(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="user_store"):
            KnowledgeManager(storage_dir=str(tmp_path / "k"))

    def test_raises_if_graph_missing(self, tmp_path) -> None:
        """Passing user_store but no graph must raise — not silently construct an unscoped graph."""
        with pytest.raises(ValueError, match="LongTermMemoryGraph"):
            KnowledgeManager(
                storage_dir=str(tmp_path / "k"),
                user_store=UserKnowledgeStore(str(tmp_path / "user")),
            )

    def test_accepts_injected_user_store_and_graph(self, tmp_path) -> None:
        store = UserKnowledgeStore(str(tmp_path / "user"))
        graph = LongTermMemoryGraph(str(tmp_path / "graph.json"))
        km = KnowledgeManager(
            storage_dir=str(tmp_path / "k"),
            user_store=store,
            graph=graph,
        )
        assert km.user_store is store
        assert km.graph is graph


# --- DF-12: profile_id keyword-only required -------------------------------


@pytest.fixture()
def mb(tmp_path):
    return MemoryBuilder(TraceConfig(episodic_storage_dir=str(tmp_path / "episodes")))


@pytest.fixture()
def kb(tmp_path):
    return KnowledgeBuilder(
        TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    )


class TestBuildShortTermStoreRejectsEmptyProfileId:
    def test_empty_string_raises(self, mb) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            mb.build_short_term_store(profile_id="")

    def test_positional_call_is_type_error(self, mb) -> None:
        """profile_id is keyword-only; positional call must fail."""
        with pytest.raises(TypeError):
            mb.build_short_term_store("leaked-profile")  # type: ignore[misc]


class TestBuildMidTermStoreRejectsEmptyProfileId:
    def test_empty_string_raises(self, mb) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            mb.build_mid_term_store(profile_id="")


class TestBuildLongTermGraphRejectsEmptyProfileId:
    def test_empty_string_raises(self, mb) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            mb.build_long_term_graph(profile_id="")


class TestBuildKnowledgeManagerRejectsEmptyProfileId:
    def test_empty_string_raises(self, kb) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            kb.build_knowledge_manager(profile_id="")

    def test_positional_profile_id_is_type_error(self, kb) -> None:
        with pytest.raises(TypeError):
            kb.build_knowledge_manager("leaked-profile")  # type: ignore[misc]

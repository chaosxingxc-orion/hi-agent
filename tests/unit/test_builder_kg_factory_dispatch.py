"""Unit: SystemBuilder dispatches to the correct KG backend per posture.

Layer 1 — Unit tests; file system is faked via tmp_path.
Mocks JsonGraphBackend.__init__ and SqliteKnowledgeGraphBackend.__init__
to avoid touching the file system.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hi_agent.config.posture import Posture
from hi_agent.memory.kg_factory import make_knowledge_graph_backend

# ---------------------------------------------------------------------------
# Helper: call factory with a given posture, capturing which class is built.
# ---------------------------------------------------------------------------

def _call_factory(posture: Posture, tmp_path: Path, env: dict | None = None):
    """Call make_knowledge_graph_backend under a given posture.

    Returns the backend instance (from the mock).
    """
    extra_env = env or {}
    with patch.dict(os.environ, extra_env, clear=False):
        backend = make_knowledge_graph_backend(
            posture=posture,
            data_dir=tmp_path,
            profile_id="prof1",
            project_id="proj1",
        )
    return backend


class TestFactoryDispatch:
    """make_knowledge_graph_backend dispatches by posture and env override."""

    def test_dev_posture_returns_json_backend(self, tmp_path):
        """Dev posture yields JsonGraphBackend (fast, file-based)."""
        from hi_agent.memory.long_term import JsonGraphBackend

        with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": ""}, clear=False):
            backend = make_knowledge_graph_backend(
                posture=Posture.DEV,
                data_dir=tmp_path,
                profile_id="prof1",
                project_id="",
            )
        assert isinstance(backend, JsonGraphBackend)

    def test_research_posture_returns_sqlite_backend(self, tmp_path):
        """Research posture yields SqliteKnowledgeGraphBackend (durable)."""
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": ""}, clear=False):
            backend = make_knowledge_graph_backend(
                posture=Posture.RESEARCH,
                data_dir=tmp_path,
                profile_id="prof1",
                project_id="",
            )
        assert isinstance(backend, SqliteKnowledgeGraphBackend)

    def test_prod_posture_returns_sqlite_backend(self, tmp_path):
        """Prod posture yields SqliteKnowledgeGraphBackend."""
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": ""}, clear=False):
            backend = make_knowledge_graph_backend(
                posture=Posture.PROD,
                data_dir=tmp_path,
                profile_id="prof1",
            )
        assert isinstance(backend, SqliteKnowledgeGraphBackend)

    def test_env_override_json_wins_over_research_posture(self, tmp_path):
        """HI_AGENT_KG_BACKEND=json forces JSON backend even under research posture."""
        from hi_agent.memory.long_term import JsonGraphBackend

        with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": "json"}, clear=False):
            backend = make_knowledge_graph_backend(
                posture=Posture.RESEARCH,
                data_dir=tmp_path,
                profile_id="prof1",
            )
        assert isinstance(backend, JsonGraphBackend)

    def test_env_override_sqlite_wins_over_dev_posture(self, tmp_path):
        """HI_AGENT_KG_BACKEND=sqlite forces SQLite backend even under dev posture."""
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": "sqlite"}, clear=False):
            backend = make_knowledge_graph_backend(
                posture=Posture.DEV,
                data_dir=tmp_path,
                profile_id="prof1",
            )
        assert isinstance(backend, SqliteKnowledgeGraphBackend)

    def test_missing_profile_id_raises(self, tmp_path):
        """Empty profile_id must raise ValueError (Rule 6 / Rule 12)."""
        with pytest.raises(ValueError, match="profile_id"):
            make_knowledge_graph_backend(
                posture=Posture.DEV,
                data_dir=tmp_path,
                profile_id="",
            )


class TestBuilderDispatch:
    """SystemBuilder.build_long_term_graph dispatches via factory."""

    def test_research_posture_wires_sqlite(self, tmp_path):
        """Under research posture, build_long_term_graph returns SQLite backend."""
        from hi_agent.config.memory_builder import MemoryBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = MemoryBuilder(config)

        with patch.dict(
            os.environ,
            {"HI_AGENT_POSTURE": "research", "HI_AGENT_KG_BACKEND": ""},
            clear=False,
        ):
            graph = builder.build_long_term_graph(profile_id="tprof")

        assert isinstance(graph, SqliteKnowledgeGraphBackend)

    def test_dev_posture_wires_json(self, tmp_path):
        """Under dev posture, build_long_term_graph returns JSON backend."""
        from hi_agent.config.memory_builder import MemoryBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.memory.long_term import JsonGraphBackend

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = MemoryBuilder(config)

        with patch.dict(
            os.environ,
            {"HI_AGENT_POSTURE": "dev", "HI_AGENT_KG_BACKEND": ""},
            clear=False,
        ):
            graph = builder.build_long_term_graph(profile_id="tprof")

        assert isinstance(graph, JsonGraphBackend)

    def test_json_env_override_under_research(self, tmp_path):
        """HI_AGENT_KG_BACKEND=json overrides research posture in builder."""
        from hi_agent.config.memory_builder import MemoryBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.memory.long_term import JsonGraphBackend

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = MemoryBuilder(config)

        with patch.dict(
            os.environ,
            {"HI_AGENT_POSTURE": "research", "HI_AGENT_KG_BACKEND": "json"},
            clear=False,
        ):
            graph = builder.build_long_term_graph(profile_id="tprof")

        assert isinstance(graph, JsonGraphBackend)

    def test_cache_returns_same_instance(self, tmp_path):
        """Repeated calls with same (profile_id, workspace_key) return the cached instance."""
        from hi_agent.config.memory_builder import MemoryBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
        builder = MemoryBuilder(config)

        env = {"HI_AGENT_POSTURE": "dev", "HI_AGENT_KG_BACKEND": ""}
        with patch.dict(os.environ, env, clear=False):
            g1 = builder.build_long_term_graph(profile_id="same")
            g2 = builder.build_long_term_graph(profile_id="same")

        assert g1 is g2

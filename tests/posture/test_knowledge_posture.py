"""Posture-matrix tests for knowledge/memory module callsites (Rule 11).

Covers:
  hi_agent/knowledge/factory.py — make_knowledge_graph_backend

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to the corresponding callsite function names.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# knowledge.factory.make_knowledge_graph_backend
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_sqlite", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_make_knowledge_graph_backend(monkeypatch, posture_name, expect_sqlite, tmp_path):
    """Posture-matrix test for make_knowledge_graph_backend.

    dev: returns JsonGraphBackend (in-memory).
    research/prod: returns SqliteKnowledgeGraphBackend (durable).
    HI_AGENT_KG_BACKEND override takes precedence over posture.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    monkeypatch.delenv("HI_AGENT_KG_BACKEND", raising=False)
    from hi_agent.knowledge.factory import make_knowledge_graph_backend
    from hi_agent.knowledge.sqlite_backend import SqliteKnowledgeGraphBackend
    from hi_agent.memory.long_term import JsonGraphBackend

    backend = make_knowledge_graph_backend(posture=Posture(posture_name), data_dir=str(tmp_path))
    if expect_sqlite:
        assert isinstance(backend, SqliteKnowledgeGraphBackend)
    else:
        assert isinstance(backend, JsonGraphBackend)

    # json override: always JsonGraphBackend
    monkeypatch.setenv("HI_AGENT_KG_BACKEND", "json")
    backend = make_knowledge_graph_backend(posture=Posture(posture_name), data_dir=str(tmp_path))
    assert isinstance(backend, JsonGraphBackend)

    # sqlite override: always SqliteKnowledgeGraphBackend
    monkeypatch.setenv("HI_AGENT_KG_BACKEND", "sqlite")
    backend = make_knowledge_graph_backend(posture=Posture(posture_name), data_dir=str(tmp_path))
    assert isinstance(backend, SqliteKnowledgeGraphBackend)

    # posture=None resolves from env
    monkeypatch.delenv("HI_AGENT_KG_BACKEND", raising=False)
    backend = make_knowledge_graph_backend(posture=None, data_dir=str(tmp_path))
    if expect_sqlite:
        assert isinstance(backend, SqliteKnowledgeGraphBackend)
    else:
        assert isinstance(backend, JsonGraphBackend)

"""Integration tests for make_knowledge_graph_backend posture-aware factory.

Layer 2 — Integration: real components wired together.  No mocks on the
subsystem under test (the factory and the backends it returns).
"""

from __future__ import annotations

import pytest
from hi_agent.knowledge.factory import make_knowledge_graph_backend
from hi_agent.knowledge.sqlite_backend import SqliteKnowledgeGraphBackend
from hi_agent.memory.long_term import JsonGraphBackend


def test_dev_gets_json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """HI_AGENT_POSTURE=dev with no override returns a JsonGraphBackend instance."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.delenv("HI_AGENT_KG_BACKEND", raising=False)

    backend = make_knowledge_graph_backend()
    assert isinstance(backend, JsonGraphBackend)


def test_sqlite_override_gets_sqlite_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """HI_AGENT_KG_BACKEND=sqlite always returns SqliteKnowledgeGraphBackend."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.setenv("HI_AGENT_KG_BACKEND", "sqlite")

    backend = make_knowledge_graph_backend(data_dir=str(tmp_path))
    assert isinstance(backend, SqliteKnowledgeGraphBackend)
    backend.close()


def test_research_posture_gets_sqlite_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """HI_AGENT_POSTURE=research with no override returns SqliteKnowledgeGraphBackend."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.delenv("HI_AGENT_KG_BACKEND", raising=False)

    backend = make_knowledge_graph_backend(data_dir=str(tmp_path))
    assert isinstance(backend, SqliteKnowledgeGraphBackend)
    backend.close()


def test_prod_posture_gets_sqlite_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """HI_AGENT_POSTURE=prod with no override returns SqliteKnowledgeGraphBackend."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    monkeypatch.delenv("HI_AGENT_KG_BACKEND", raising=False)

    backend = make_knowledge_graph_backend(data_dir=str(tmp_path))
    assert isinstance(backend, SqliteKnowledgeGraphBackend)
    backend.close()


def test_json_override_beats_strict_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HI_AGENT_KG_BACKEND=json override returns JsonGraphBackend even under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_KG_BACKEND", "json")

    backend = make_knowledge_graph_backend()
    assert isinstance(backend, JsonGraphBackend)


def test_factory_uses_posture_from_env_when_none_passed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Passing posture=None causes factory to resolve from env via Posture.from_env."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "sqlite")
    monkeypatch.setenv("HI_AGENT_KG_BACKEND", "sqlite")

    # Posture.from_env will raise on unknown value; we catch and assert the error.
    with pytest.raises(ValueError, match="HI_AGENT_POSTURE"):
        make_knowledge_graph_backend(posture=None, data_dir=str(tmp_path))


def test_factory_explicit_posture_overrides_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Explicit posture= argument overrides HI_AGENT_POSTURE env var."""
    from hi_agent.config.posture import Posture

    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.delenv("HI_AGENT_KG_BACKEND", raising=False)

    backend = make_knowledge_graph_backend(posture=Posture.DEV)
    assert isinstance(backend, JsonGraphBackend)

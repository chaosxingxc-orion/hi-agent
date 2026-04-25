"""Unit tests: KnowledgeManager must fail-fast when graph is not injected.

Guards Rule 6 — inline fallback construction of unscoped LongTermMemoryGraph
is forbidden.  SA-A7 residual (knowledge_manager.py path).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.knowledge.knowledge_manager import KnowledgeManager
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore


def _make_user_store() -> UserKnowledgeStore:
    """Minimal injected user_store for KnowledgeManager construction."""
    store = MagicMock(spec=UserKnowledgeStore)
    return store


def test_knowledge_manager_raises_on_missing_graph() -> None:
    """KnowledgeManager must raise ValueError when graph is not injected.

    The LongTermMemoryGraph must always be provided by build_knowledge_manager().
    Omitting it is a wiring bug — fail-fast rather than constructing an unscoped
    instance.
    """
    user_store = _make_user_store()

    with pytest.raises(ValueError, match="LongTermMemoryGraph"):
        KnowledgeManager(user_store=user_store, graph=None)


def test_knowledge_manager_raises_on_missing_user_store() -> None:
    """KnowledgeManager must raise ValueError when user_store is not injected."""
    with pytest.raises(ValueError, match="user_store"):
        KnowledgeManager(user_store=None, graph=None)


def test_knowledge_manager_raises_on_missing_graph_mentions_builder() -> None:
    """The ValueError for missing graph must name the builder function."""
    user_store = _make_user_store()

    with pytest.raises(ValueError, match="build_knowledge_manager"):
        KnowledgeManager(user_store=user_store, graph=None)


def test_knowledge_manager_constructs_when_all_injected() -> None:
    """KnowledgeManager must construct successfully when all dependencies are injected."""
    from hi_agent.knowledge.graph_renderer import GraphRenderer
    from hi_agent.knowledge.wiki import KnowledgeWiki
    from hi_agent.memory.long_term import LongTermMemoryGraph

    user_store = _make_user_store()
    graph = MagicMock(spec=LongTermMemoryGraph)
    wiki = MagicMock(spec=KnowledgeWiki)
    renderer = MagicMock(spec=GraphRenderer)

    manager = KnowledgeManager(
        wiki=wiki,
        user_store=user_store,
        graph=graph,
        renderer=renderer,
    )

    assert manager._user_store is user_store
    assert manager._graph is graph
    assert manager._wiki is wiki
    assert manager._renderer is renderer

"""Unit tests: KnowledgeManager raises ValueError for each missing required injection.

Guards Rule 6 (H2-Track3) — both inline fallback constructions removed:
  wiki, renderer.
Each must fail fast with a clear ValueError when not explicitly injected.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.knowledge_manager import KnowledgeManager
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
from hi_agent.knowledge.wiki import KnowledgeWiki
from hi_agent.memory.long_term import LongTermMemoryGraph


def _base_kwargs() -> dict:
    """Return all required args so individual tests can omit one at a time."""
    graph = MagicMock(spec=LongTermMemoryGraph)
    return {
        "wiki": MagicMock(spec=KnowledgeWiki),
        "user_store": MagicMock(spec=UserKnowledgeStore),
        "graph": graph,
        "renderer": MagicMock(spec=GraphRenderer),
    }


# ---------------------------------------------------------------------------
# wiki
# ---------------------------------------------------------------------------


def test_knowledge_manager_raises_on_missing_wiki() -> None:
    """KnowledgeManager must raise ValueError when wiki=None.

    Rule 6: unscoped KnowledgeWiki inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["wiki"] = None
    with pytest.raises(ValueError, match="wiki"):
        KnowledgeManager(**kwargs)


def test_knowledge_manager_wiki_error_mentions_rule6() -> None:
    """ValueError for missing wiki must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["wiki"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        KnowledgeManager(**kwargs)


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------


def test_knowledge_manager_raises_on_missing_renderer() -> None:
    """KnowledgeManager must raise ValueError when renderer=None.

    Rule 6: unscoped GraphRenderer inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["renderer"] = None
    with pytest.raises(ValueError, match="renderer"):
        KnowledgeManager(**kwargs)


def test_knowledge_manager_renderer_error_mentions_rule6() -> None:
    """ValueError for missing renderer must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["renderer"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        KnowledgeManager(**kwargs)


# ---------------------------------------------------------------------------
# Positive: all args provided → construction succeeds
# ---------------------------------------------------------------------------


def test_knowledge_manager_constructs_successfully_with_all_required_args() -> None:
    """KnowledgeManager must construct without error when all args are injected."""
    kwargs = _base_kwargs()
    km = KnowledgeManager(**kwargs)
    assert km._wiki is kwargs["wiki"]
    assert km._user_store is kwargs["user_store"]
    assert km._graph is kwargs["graph"]
    assert km._renderer is kwargs["renderer"]

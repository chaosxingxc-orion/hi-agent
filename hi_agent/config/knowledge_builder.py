"""KnowledgeBuilder - extracted from the central builder (HI-W7-001).

Builds wiki, user knowledge store, and knowledge manager.
Takes TraceConfig plus an optional long-term graph factory callable.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.observability.metric_counter import Counter

logger = logging.getLogger(__name__)
_knowledge_builder_errors_total = Counter("hi_agent_knowledge_builder_errors_total")


class KnowledgeBuilder:
    """Build wiki, user knowledge store, and knowledge manager."""

    def __init__(
        self,
        config: TraceConfig,
        long_term_graph_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._config = config
        self._long_term_graph_factory = long_term_graph_factory

    def _knowledge_base_dir(self) -> str:
        return self._config.episodic_storage_dir.replace("episodes", "")

    def build_knowledge_wiki(self) -> Any:
        from hi_agent.knowledge.wiki import KnowledgeWiki

        wiki = KnowledgeWiki(os.path.join(self._knowledge_base_dir(), "knowledge", "wiki"))
        try:
            wiki.load()
        except (FileNotFoundError, KeyError, ValueError):  # rule7-exempt: expiry_wave="Wave 29"
            pass  # expected on fresh installs
        except Exception as exc:
            _knowledge_builder_errors_total.inc()
            logger.warning("build_knowledge_wiki: failed to load prior wiki state: %s", exc)
        return wiki

    def build_user_knowledge_store(self) -> Any:
        from hi_agent.knowledge.user_knowledge import UserKnowledgeStore

        return UserKnowledgeStore(os.path.join(self._knowledge_base_dir(), "knowledge", "user"))

    def build_knowledge_manager(
        self,
        *,
        profile_id: str,
        long_term_graph: Any = None,
    ) -> Any:
        """Build KnowledgeManager scoped to ``profile_id``.

        Rule 13 (DF-12): ``profile_id`` is keyword-only and required. Empty
        string is rejected because the silent default path produced a
        KnowledgeManager pointing at an unscoped knowledge directory — the
        recurring F-2/G-5/I-7 defect shape.
        """
        from hi_agent.knowledge.graph_renderer import GraphRenderer
        from hi_agent.knowledge.knowledge_manager import KnowledgeManager

        if not profile_id:
            raise ValueError(
                "build_knowledge_manager requires profile_id; empty string "
                "was masking cross-profile knowledge leakage in Rounds 4/5/7 "
                "(Rule 13 / DF-12)."
            )
        wiki = self.build_knowledge_wiki()
        user_store = self.build_user_knowledge_store()
        if long_term_graph is None and self._long_term_graph_factory is not None:
            long_term_graph = self._long_term_graph_factory(profile_id)
        if long_term_graph is None:
            raise ValueError(
                "build_knowledge_manager requires a LongTermMemoryGraph; "
                "pass long_term_graph= or supply a long_term_graph_factory "
                "at KnowledgeBuilder construction time (Rule 13 / J7-1)."
            )
        renderer = GraphRenderer(long_term_graph)
        return KnowledgeManager(
            wiki=wiki,
            user_store=user_store,
            graph=long_term_graph,
            renderer=renderer,
        )

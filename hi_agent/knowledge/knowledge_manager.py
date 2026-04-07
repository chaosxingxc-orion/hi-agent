"""Unified knowledge manager coordinating all knowledge types.

Provides a single interface for:
- Ingesting new knowledge (from runs, user input, documents)
- Querying across all knowledge sources
- Maintaining knowledge health (lint, consolidation)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from hi_agent.knowledge.graph_renderer import GraphRenderer
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode


@dataclass
class KnowledgeResult:
    """Unified query result from all knowledge sources."""

    wiki_pages: list[WikiPage] = field(default_factory=list)
    graph_nodes: list[MemoryNode] = field(default_factory=list)
    user_context: str = ""
    total_results: int = 0

    def to_context_string(self, max_tokens: int = 1500) -> str:
        """Format all results for LLM consumption."""
        parts: list[str] = []
        budget = max_tokens * 4
        used = 0

        # User context first (short)
        if self.user_context:
            section = f"### User Context\n{self.user_context}\n\n"
            if used + len(section) <= budget:
                parts.append(section)
                used += len(section)

        # Wiki pages
        if self.wiki_pages:
            for page in self.wiki_pages:
                section = f"### {page.title}\n{page.content}\n\n"
                if used + len(section) > budget:
                    break
                parts.append(section)
                used += len(section)

        # Graph nodes
        if self.graph_nodes:
            node_lines: list[str] = []
            for node in self.graph_nodes:
                line = f"- [{node.node_type}] {node.content}"
                if used + len(line) + 1 > budget:
                    break
                node_lines.append(line)
                used += len(line) + 1
            if node_lines:
                parts.append("### Knowledge Graph\n" + "\n".join(node_lines) + "\n")

        return "".join(parts)


class KnowledgeManager:
    """Unified knowledge manager."""

    def __init__(
        self,
        wiki: KnowledgeWiki | None = None,
        user_store: UserKnowledgeStore | None = None,
        graph: LongTermMemoryGraph | None = None,
        renderer: GraphRenderer | None = None,
        storage_dir: str = ".hi_agent/knowledge",
    ) -> None:
        self._storage_dir = storage_dir
        self._wiki = wiki or KnowledgeWiki(f"{storage_dir}/wiki")
        self._user_store = user_store or UserKnowledgeStore(f"{storage_dir}/user")
        self._graph = graph or LongTermMemoryGraph(f"{storage_dir}/graph.json")
        self._renderer = renderer or GraphRenderer(self._graph)

    @property
    def wiki(self) -> KnowledgeWiki:
        return self._wiki

    @property
    def user_store(self) -> UserKnowledgeStore:
        return self._user_store

    @property
    def graph(self) -> LongTermMemoryGraph:
        return self._graph

    @property
    def renderer(self) -> GraphRenderer:
        return self._renderer

    # ------------------------------------------------------------------ Ingest

    def ingest_from_session(self, session: Any) -> int:
        """Extract knowledge from a completed session.
        Creates wiki pages for key findings, updates user profile,
        adds facts to graph. Returns items ingested."""
        count = 0
        # Session is expected to have: findings, user_feedback, facts
        findings: list[str] = getattr(session, "findings", [])
        for finding in findings:
            page_id = f"finding-{uuid.uuid4().hex[:8]}"
            page = WikiPage(
                page_id=page_id,
                title=finding[:80],
                content=finding,
                page_type="summary",
                tags=["session-finding"],
            )
            self._wiki.add_page(page)
            count += 1

        user_feedback: list[str] = getattr(session, "user_feedback", [])
        for fb in user_feedback:
            self._user_store.add_feedback(fb)
            count += 1

        facts: list[dict[str, Any]] = getattr(session, "facts", [])
        count += self.ingest_structured(facts)

        return count

    def ingest_text(
        self, title: str, content: str, tags: list[str] | None = None
    ) -> str:
        """Ingest free-text knowledge. Creates a wiki page. Returns page_id."""
        page_id = _slugify(title)
        page = WikiPage(
            page_id=page_id,
            title=title,
            content=content,
            page_type="concept",
            tags=tags or [],
        )
        self._wiki.add_page(page)
        self._wiki.append_log("ingest_text", f"Created page '{page_id}'")
        return page_id

    def ingest_structured(self, facts: list[dict[str, Any]]) -> int:
        """Ingest structured facts into graph.
        Each fact: {"content": "...", "type": "fact|method|rule", "tags": [...]}
        Returns nodes created."""
        count = 0
        for fact in facts:
            content = fact.get("content", "")
            if not content:
                continue
            node = MemoryNode(
                node_id=uuid.uuid4().hex[:12],
                content=content,
                node_type=fact.get("type", "fact"),
                tags=fact.get("tags", []),
            )
            self._graph.add_node(node)
            count += 1
        return count

    # ------------------------------------------------------------------ Query

    def query(self, query: str, limit: int = 10) -> KnowledgeResult:
        """Search across wiki, graph, and user knowledge.
        Returns ranked results from all sources."""
        wiki_pages = self._wiki.search(query, limit=limit)
        graph_nodes = self._graph.search(query, limit=limit)
        user_context = self._user_store.to_context_string()

        return KnowledgeResult(
            wiki_pages=wiki_pages,
            graph_nodes=graph_nodes,
            user_context=user_context,
            total_results=len(wiki_pages) + len(graph_nodes),
        )

    def query_for_context(self, query: str, budget_tokens: int = 1500) -> str:
        """Query and format results for direct LLM context injection.
        Combines: user profile + relevant wiki pages + graph nodes."""
        result = self.query(query)
        return result.to_context_string(max_tokens=budget_tokens)

    # ------------------------------------------------------------------ Maintenance

    def lint(self) -> list[str]:
        """Run health checks across all knowledge sources."""
        issues: list[str] = []
        issues.extend(self._wiki.lint())
        return issues

    def get_stats(self) -> dict[str, Any]:
        """Return stats: page count, node count, edge count, user prefs count."""
        profile = self._user_store.get_profile()
        return {
            "wiki_pages": len(self._wiki.list_pages()),
            "graph_nodes": self._graph.node_count(),
            "graph_edges": self._graph.edge_count(),
            "user_preferences": len(profile.preferences),
            "user_expertise_areas": len(profile.expertise),
        }


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = slug.replace(" ", "-")
    # Keep only alphanumeric and hyphens
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60].strip("-") or "untitled"

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


# W31 T-24' decision: in-process query response wrapper; tenant-agnostic.
# scope: process-internal
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
        """Initialize KnowledgeManager.

        Rule 6/13 (DF-11, J7-1): all four shared resources — ``wiki``,
        ``user_store``, ``graph``, and ``renderer`` — must be injected by
        ``build_knowledge_manager(...)``. Inline fallback construction of any
        of these diverges from the builder's profile-scoped instances
        (Rule 6 / Rule 13 / H2-Track3).
        """
        if user_store is None:
            raise ValueError(
                "KnowledgeManager requires an injected user_store; inline "
                "fallback diverged from the builder's shared instance "
                "(Rule 13 / DF-11)."
            )
        if graph is None:
            raise ValueError(
                "KnowledgeManager requires a LongTermMemoryGraph — use "
                "build_knowledge_manager(...) builder which provides a "
                "scoped graph (Rule 13 / J7-1)."
            )
        self._storage_dir = storage_dir
        if wiki is None:
            raise ValueError(
                "KnowledgeManager.wiki must be injected by the builder — "
                "unscoped KnowledgeWiki is not permitted (Rule 6). "
                "Pass wiki=KnowledgeWiki(storage_dir/wiki) explicitly."
            )
        self._wiki = wiki
        self._user_store = user_store
        self._graph = graph
        if renderer is None:
            raise ValueError(
                "KnowledgeManager.renderer must be injected by the builder — "
                "unscoped GraphRenderer is not permitted (Rule 6). "
                "Pass renderer=GraphRenderer(graph) explicitly."
            )
        self._renderer = renderer

    @property
    def wiki(self) -> KnowledgeWiki:
        """Return wiki."""
        return self._wiki

    @property
    def user_store(self) -> UserKnowledgeStore:
        """Return user_store."""
        return self._user_store

    @property
    def graph(self) -> LongTermMemoryGraph:
        """Return graph."""
        return self._graph

    @property
    def renderer(self) -> GraphRenderer:
        """Return renderer."""
        return self._renderer

    # ------------------------------------------------------------------ Ingest

    def ingest_from_session(self, session: Any) -> int:
        """Extract knowledge from a completed session and return ingest count."""
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
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> str:
        """Ingest free-text knowledge. Creates a wiki page. Returns page_id.

        W32 Track B Gap 6 (W33 T-9'/T-10'): callers MUST provide
        ``tenant_id`` so write-path attribution is tracked. Strict posture
        rejects an absent value; dev posture emits a WARNING and proceeds
        for back-compat.

        Note: the underlying wiki store is process-internal and does not
        partition by tenant. Per-tenant partitioning is a store-level
        concern tracked separately. Manager-level acceptance is the
        prerequisite for that follow-up.
        """
        self._require_tenant_for_write(tenant_id, op="ingest_text")
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

    def ingest_structured(
        self,
        facts: list[dict[str, Any]],
        *,
        tenant_id: str | None = None,
    ) -> int:
        """Ingest structured facts into graph and return created node count.

        W32 Track B Gap 6 (W33 T-9'/T-10'): callers MUST provide
        ``tenant_id`` so write-path attribution is tracked. Strict posture
        rejects an absent value; dev posture emits a WARNING and proceeds
        for back-compat.
        """
        self._require_tenant_for_write(tenant_id, op="ingest_structured")
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

    def query(
        self,
        query: str,
        limit: int = 10,
        *,
        tenant_id: str | None = None,
    ) -> KnowledgeResult:
        """Search across wiki, graph, and user knowledge.

        Tenant scope (W31, T-2'): callers MUST provide ``tenant_id`` so the
        manager can scope reads. Under research/prod posture, missing
        ``tenant_id`` raises :class:`~hi_agent.errors.categories.TenantScopeError`
        — silent cross-tenant reads are forbidden. Under dev posture a missing
        value emits a WARNING log (back-compat).

        Note: the underlying wiki/graph stores do not yet filter by
        ``tenant_id`` (tracked separately as a store-level concern). Manager
        signature acceptance is the prerequisite for a follow-up store-level
        partitioning change.
        """
        self._require_tenant_for_read(tenant_id, op="query")
        wiki_pages = self._wiki.search(query, limit=limit)
        graph_nodes = self._graph.search(query, limit=limit)
        user_context = self._user_store.to_context_string()

        return KnowledgeResult(
            wiki_pages=wiki_pages,
            graph_nodes=graph_nodes,
            user_context=user_context,
            total_results=len(wiki_pages) + len(graph_nodes),
        )

    def query_for_context(
        self,
        query: str,
        budget_tokens: int = 1500,
        *,
        tenant_id: str | None = None,
    ) -> str:
        """Query and format results for direct LLM context injection.

        Tenant scope: see :meth:`query`. Strict posture requires ``tenant_id``.
        """
        self._require_tenant_for_read(tenant_id, op="query_for_context")
        # Pass tenant_id through so the inner query() call also enforces.
        result = self.query(query, tenant_id=tenant_id)
        return result.to_context_string(max_tokens=budget_tokens)

    # ------------------------------------------------------------------ Maintenance

    def lint(self, *, tenant_id: str | None = None) -> list[str]:
        """Run health checks across all knowledge sources.

        Tenant scope: see :meth:`query`. Strict posture requires ``tenant_id``.
        """
        self._require_tenant_for_read(tenant_id, op="lint")
        issues: list[str] = []
        issues.extend(self._wiki.lint())
        return issues

    def get_stats(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        """Return stats: page count, node count, edge count, user prefs count.

        Tenant scope: see :meth:`query`. Strict posture requires ``tenant_id``.
        """
        self._require_tenant_for_read(tenant_id, op="get_stats")
        profile = self._user_store.get_profile()
        return {
            "wiki_pages": len(self._wiki.list_pages()),
            "graph_nodes": self._graph.node_count(),
            "graph_edges": self._graph.edge_count(),
            "user_preferences": len(profile.preferences),
            "user_expertise_areas": len(profile.expertise),
        }

    @staticmethod
    def _require_tenant_for_read(tenant_id: str | None, *, op: str) -> None:
        """Validate tenant_id presence according to current posture (W31).

        Under research/prod posture, raise TenantScopeError if missing.
        Under dev posture, log a WARNING and proceed (back-compat).
        """
        import logging

        from hi_agent.config.posture import Posture
        from hi_agent.contracts.errors import TenantScopeError

        if tenant_id and tenant_id.strip():
            return
        posture = Posture.from_env()
        msg = (
            f"KnowledgeManager.{op}: tenant_id is missing or empty; "
            "cross-tenant reads are forbidden under research/prod posture."
        )
        if posture.is_strict:
            raise TenantScopeError(msg)
        logging.getLogger(__name__).warning(msg)

    @staticmethod
    def _require_tenant_for_write(tenant_id: str | None, *, op: str) -> None:
        """Validate tenant_id presence on write paths (W32 Track B Gap 6).

        Under research/prod posture, raise TenantScopeError if missing.
        Under dev posture, log a WARNING and proceed (back-compat).
        """
        import logging

        from hi_agent.config.posture import Posture
        from hi_agent.contracts.errors import TenantScopeError

        if tenant_id and tenant_id.strip():
            return
        posture = Posture.from_env()
        msg = (
            f"KnowledgeManager.{op}: tenant_id is missing or empty; "
            "cross-tenant writes are forbidden under research/prod posture."
        )
        if posture.is_strict:
            raise TenantScopeError(msg)
        logging.getLogger(__name__).warning(msg)


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

"""Render knowledge graph as Mermaid diagrams and Markdown wiki.

Three output formats:
1. Mermaid: For visualization (human-readable diagrams)
2. Markdown Wiki: For LLM consumption (interlinked pages)
3. Plain text: For direct LLM context injection
"""

from __future__ import annotations

import re

from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode


class GraphRenderer:
    """Render LongTermMemoryGraph in various formats."""

    def __init__(self, graph: LongTermMemoryGraph) -> None:
        """Initialize GraphRenderer."""
        self._graph = graph

    def to_mermaid(self, max_nodes: int = 50, node_type: str | None = None) -> str:
        """Render graph as Mermaid flowchart.

        Example output:
        ```mermaid
        graph TD
            A[Revenue Analysis] -->|supports| B[Q4 Growth]
            A -->|contradicts| C[Cost Concerns]
        ```
        """
        # Collect nodes
        nodes: list[MemoryNode] = []
        for _nid, node in self._graph.iter_nodes():
            if node_type is not None and node.node_type != node_type:
                continue
            nodes.append(node)
            if len(nodes) >= max_nodes:
                break

        if not nodes:
            return "```mermaid\ngraph TD\n    empty[No nodes]\n```"

        node_ids = {n.node_id for n in nodes}
        lines = ["```mermaid", "graph TD"]

        # Declare nodes
        for node in nodes:
            safe_id = self._sanitize_mermaid_id(node.node_id)
            safe_label = self._sanitize_mermaid_label(node.content[:60])
            lines.append(f"    {safe_id}[{safe_label}]")

        # Add edges
        for edge in self._graph._edges:
            if edge.source_id in node_ids and edge.target_id in node_ids:
                src = self._sanitize_mermaid_id(edge.source_id)
                tgt = self._sanitize_mermaid_id(edge.target_id)
                rel = self._sanitize_mermaid_label(edge.relation_type)
                lines.append(f"    {src} -->|{rel}| {tgt}")

        lines.append("```")
        return "\n".join(lines)

    def to_mermaid_mindmap(self, root_id: str, depth: int = 3) -> str:
        """Render subgraph as Mermaid mindmap from a root node."""
        root = self._graph.get_node(root_id)
        if root is None:
            return "```mermaid\nmindmap\n  root((empty))\n```"

        nodes, edges = self._graph.get_subgraph(root_id, depth=depth)
        if not nodes:
            return "```mermaid\nmindmap\n  root((empty))\n```"

        # Build adjacency for BFS ordering
        children: dict[str, list[str]] = {}
        for edge in edges:
            children.setdefault(edge.source_id, []).append(edge.target_id)
            children.setdefault(edge.target_id, []).append(edge.source_id)

        node_map = {n.node_id: n for n in nodes}
        lines = ["```mermaid", "mindmap"]
        root_label = self._sanitize_mermaid_label(root.content[:50])
        lines.append(f"  root(({root_label}))")

        # BFS to build tree (avoid cycles)
        visited = {root_id}
        frontier = [root_id]
        indent = 4

        while frontier:
            next_frontier: list[str] = []
            for nid in frontier:
                for child_id in children.get(nid, []):
                    if child_id not in visited:
                        visited.add(child_id)
                        child_node = node_map.get(child_id)
                        if child_node:
                            label = self._sanitize_mermaid_label(child_node.content[:50])
                            lines.append(f"{' ' * indent}{label}")
                        next_frontier.append(child_id)
            frontier = next_frontier
            indent += 2

        lines.append("```")
        return "\n".join(lines)

    def to_wiki_pages(self, wiki: KnowledgeWiki) -> int:
        """Convert graph nodes to wiki pages with wikilinks and return count."""
        count = 0
        for _nid, node in self._graph.iter_nodes():
            # Build content with wikilinks to neighbors
            neighbors = self._graph.get_neighbors(node.node_id)
            content = node.content
            if neighbors:
                links = ", ".join(f"[[{n.node_id}]]" for n in neighbors)
                content += f"\n\nRelated: {links}"

            existing = wiki.get_page(node.node_id)
            if existing is not None:
                wiki.update_page(node.node_id, content=content, tags=node.tags)
            else:
                page = WikiPage(
                    page_id=node.node_id,
                    title=node.content[:80],
                    content=content,
                    page_type=node.node_type,
                    tags=node.tags,
                    confidence=node.confidence,
                )
                wiki.add_page(page)
            count += 1
        return count

    def to_context_string(self, query: str, max_tokens: int = 1000) -> str:
        """Search graph and format matching nodes + neighbors as text."""
        if not query.strip():
            return ""

        results = self._graph.search(query, limit=5)
        if not results:
            return ""

        parts: list[str] = []
        budget = max_tokens * 4
        used = 0

        for node in results:
            section = f"- [{node.node_type}] {node.content}"
            neighbors = self._graph.get_neighbors(node.node_id)
            if neighbors:
                neighbor_strs = [n.content[:50] for n in neighbors[:3]]
                section += f" (related: {', '.join(neighbor_strs)})"
            section += "\n"
            if used + len(section) > budget:
                break
            parts.append(section)
            used += len(section)

        return "".join(parts)

    @staticmethod
    def _sanitize_mermaid_id(node_id: str) -> str:
        """Clean node_id for mermaid syntax (alphanumeric + underscore only)."""
        return re.sub(r"[^a-zA-Z0-9_]", "_", node_id)

    @staticmethod
    def _sanitize_mermaid_label(label: str) -> str:
        """Escape special chars in mermaid labels."""
        # Remove chars that break mermaid syntax
        label = label.replace("[", "(").replace("]", ")")
        label = label.replace("{", "(").replace("}", ")")
        label = label.replace('"', "'")
        label = label.replace("|", "/")
        label = label.replace("<", "").replace(">", "")
        return label

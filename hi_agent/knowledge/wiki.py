"""Wiki-based knowledge representation for LLM consumption.

Inspired by Karpathy's LLM Wiki pattern: interlinked markdown pages
with YAML frontmatter, wikilinks [[page-name]], and provenance tracking.
LLMs can both READ and WRITE these pages.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hi_agent.observability.silent_degradation import record_silent_degradation

logger = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class WikiPage:
    """A single knowledge page in the wiki."""

    page_id: str  # slug: "revenue-analysis-q4"
    title: str  # "Revenue Analysis Q4 2026"
    content: str  # markdown body with [[wikilinks]]
    page_type: str = "concept"  # concept, entity, method, summary, user_pref
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # provenance
    outgoing_links: list[str] = field(default_factory=list)  # [[linked-page-ids]]
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""


class KnowledgeWiki:
    """File-based wiki for LLM-consumable knowledge.

    Structure:
      wiki_dir/
        index.md       - catalog of all pages with summaries
        log.md         - append-only operation log (ingest, query, lint)
        pages/
          page-slug.md - individual wiki pages

    Operations (from Karpathy pattern):
      - ingest: Process source -> extract entities/concepts -> create/update pages
      - query: Search pages -> return relevant knowledge with [[links]]
      - lint: Check for contradictions, orphan pages, stale claims
    """

    def __init__(self, wiki_dir: str = ".hi_agent/knowledge/wiki") -> None:
        """Initialize KnowledgeWiki."""
        self._wiki_dir = Path(wiki_dir)
        self._pages: dict[str, WikiPage] = {}

    # ------------------------------------------------------------------ CRUD

    def add_page(self, page: WikiPage) -> None:
        """Add a wiki page. Sets timestamps if missing."""
        now = datetime.now(UTC).isoformat()
        if not page.created_at:
            page.created_at = now
        if not page.updated_at:
            page.updated_at = now
        # Auto-extract outgoing links from content
        page.outgoing_links = self.extract_links(page.content)
        self._pages[page.page_id] = page

    def update_page(
        self,
        page_id: str,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Update an existing page's content and/or tags."""
        page = self._pages.get(page_id)
        if page is None:
            return
        if content is not None:
            page.content = content
            page.outgoing_links = self.extract_links(content)
        if tags is not None:
            page.tags = tags
        page.updated_at = datetime.now(UTC).isoformat()

    def get_page(self, page_id: str) -> WikiPage | None:
        """Get a page by ID."""
        return self._pages.get(page_id)

    def remove_page(self, page_id: str) -> None:
        """Remove a page by ID."""
        self._pages.pop(page_id, None)

    def list_pages(self, page_type: str | None = None) -> list[WikiPage]:
        """List all pages, optionally filtered by type."""
        pages = list(self._pages.values())
        if page_type is not None:
            pages = [p for p in pages if p.page_type == page_type]
        return sorted(pages, key=lambda p: p.page_id)

    # ------------------------------------------------------------------ Search

    def search(self, query: str, limit: int = 10) -> list[WikiPage]:
        """Search by keyword match on title + content + tags."""
        if not query.strip():
            return []
        keywords = query.lower().split()
        scored: list[tuple[float, WikiPage]] = []
        for page in self._pages.values():
            text = (page.title + " " + page.content + " " + " ".join(page.tags)).lower()
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                scored.append((hits, page))
        scored.sort(key=lambda pair: (-pair[0], pair[1].page_id))
        return [page for _, page in scored[:limit]]

    def get_linked_pages(self, page_id: str) -> list[WikiPage]:
        """Get all pages linked from the given page via [[wikilinks]]."""
        page = self._pages.get(page_id)
        if page is None:
            return []
        result: list[WikiPage] = []
        for link_id in page.outgoing_links:
            linked = self._pages.get(link_id)
            if linked is not None:
                result.append(linked)
        return result

    # ------------------------------------------------------------------ Wikilink resolution

    def resolve_links(self, content: str) -> str:
        """Replace [[page-id]] with page title for display."""

        def _replacer(match: re.Match[str]) -> str:
            pid = match.group(1)
            page = self._pages.get(pid)
            if page is not None:
                return page.title
            return match.group(0)  # keep unresolved

        return _WIKILINK_RE.sub(_replacer, content)

    @staticmethod
    def extract_links(content: str) -> list[str]:
        """Extract all [[page-id]] references from content."""
        return _WIKILINK_RE.findall(content)

    # ------------------------------------------------------------------ Index & Log

    def rebuild_index(self) -> str:
        """Regenerate index.md with all pages listed and write it to disk."""
        lines = ["# Knowledge Wiki Index", ""]
        for page in sorted(self._pages.values(), key=lambda p: p.page_id):
            tags_str = ", ".join(page.tags) if page.tags else "none"
            lines.append(
                f"- **[{page.title}]({page.page_id}.md)** ({page.page_type}) - tags: {tags_str}"
            )
        lines.append("")
        index_content = "\n".join(lines)
        index_path = self._wiki_dir / "index.md"
        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(index_content, encoding="utf-8")
            logger.debug(
                "wiki.rebuild_index: wrote %d chars to %s",
                len(index_content),
                index_path,
            )
        except OSError as exc:
            logger.warning("wiki.rebuild_index: failed to persist index: %s", exc)
        return index_content

    def append_log(self, operation: str, details: str) -> None:
        """Append to log.md."""
        now = datetime.now(UTC).isoformat()
        log_path = self._wiki_dir / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"- [{now}] **{operation}**: {details}\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(entry)

    # ------------------------------------------------------------------ Lint

    def lint(self) -> list[str]:
        """Lint wiki pages and return orphan, broken-link, and stale issues."""
        issues: list[str] = []

        # Build incoming link map
        incoming: dict[str, int] = dict.fromkeys(self._pages, 0)
        for page in self._pages.values():
            for link_id in page.outgoing_links:
                if link_id in incoming:
                    incoming[link_id] += 1

        # Orphan pages (no incoming links, more than 1 page total)
        if len(self._pages) > 1:
            for pid, count in sorted(incoming.items()):
                if count == 0:
                    issues.append(f"orphan: '{pid}' has no incoming links")

        # Broken links
        for page in self._pages.values():
            for link_id in page.outgoing_links:
                if link_id not in self._pages:
                    issues.append(
                        f"broken_link: '{page.page_id}' links to non-existent '{link_id}'"
                    )

        # Stale pages (updated_at older than 30 days)
        now = datetime.now(UTC)
        for page in self._pages.values():
            if page.updated_at:
                try:
                    updated = datetime.fromisoformat(page.updated_at)
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=UTC)
                    delta = now - updated
                    if delta.days > 30:
                        issues.append(f"stale: '{page.page_id}' not updated in {delta.days} days")
                except (ValueError, TypeError) as exc:
                    record_silent_degradation(
                        component="knowledge.wiki.WikiKnowledgeBase._check_staleness",
                        reason="staleness_datetime_parse_failed",
                        exc=exc,
                    )

        return issues

    # ------------------------------------------------------------------ Persistence

    def save(self) -> None:
        """Write all pages to disk as JSON (one file per page + index)."""
        pages_dir = self._wiki_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        for page in self._pages.values():
            page_path = pages_dir / f"{page.page_id}.json"
            page_path.write_text(
                json.dumps(asdict(page), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        # Write index
        index_path = self._wiki_dir / "index.md"
        index_path.write_text(self.rebuild_index(), encoding="utf-8")

    def load(self) -> None:
        """Load all pages from disk."""
        pages_dir = self._wiki_dir / "pages"
        if not pages_dir.exists():
            return
        self._pages.clear()
        for page_file in sorted(pages_dir.glob("*.json")):
            try:
                data = json.loads(page_file.read_text(encoding="utf-8"))
                page = WikiPage(
                    page_id=data["page_id"],
                    title=data["title"],
                    content=data["content"],
                    page_type=data.get("page_type", "concept"),
                    tags=data.get("tags", []),
                    sources=data.get("sources", []),
                    outgoing_links=data.get("outgoing_links", []),
                    confidence=data.get("confidence", 1.0),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning(
                    "WikiStore.load: skipping corrupt page file %s: %s", page_file.name, exc
                )
                continue
            self._pages[page.page_id] = page

    # ------------------------------------------------------------------ LLM-friendly output

    def to_context_string(self, page_ids: list[str], max_tokens: int = 2000) -> str:
        """Format selected pages as context for LLM injection."""
        parts: list[str] = []
        budget = max_tokens * 4  # rough chars-per-token estimate
        used = 0

        for pid in page_ids:
            page = self._pages.get(pid)
            if page is None:
                continue
            section = f"## {page.title}\n{page.content}\n"
            if used + len(section) > budget:
                break
            parts.append(section)
            used += len(section)

        return "\n".join(parts) if parts else ""

"""Wiki-based knowledge representation for LLM consumption.

Inspired by Karpathy's LLM Wiki pattern: interlinked markdown pages
with YAML frontmatter, wikilinks [[page-name]], and provenance tracking.
LLMs can both READ and WRITE these pages.

W34-F.4 (B-W34-3): tenant partition. Every ``WikiPage`` carries a
``tenant_id``; every public read/write on ``KnowledgeWiki`` requires the
caller to declare which tenant it is acting on. Persistent storage is
laid out as ``<wiki_dir>/<tenant_id>/<page_id>.json`` so cross-tenant
reads are structurally denied (the wrong tenant's directory simply does
not contain the page). Under dev posture, a missing ``tenant_id`` emits
a WARNING and falls back to the ``"default"`` tenant for back-compat.
Under research/prod posture, a missing ``tenant_id`` raises
``ValueError``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hi_agent.config.posture import Posture
from hi_agent.observability.silent_degradation import record_silent_degradation

logger = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Sentinel directory name used under dev posture when a caller does not
# pass an explicit ``tenant_id``. Strict postures (research/prod) reject
# missing ``tenant_id`` outright and never write to this directory.
_DEFAULT_TENANT = "default"


@dataclass
class WikiPage:
    """A single knowledge page in the wiki.

    Spine: every page carries a ``tenant_id``. The dataclass enforces a
    non-empty value under research/prod posture via ``__post_init__``;
    under dev posture an empty value is permitted (the wiki layer logs a
    warning and falls back to the ``"default"`` tenant on persistence).
    """

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
    tenant_id: str = ""  # spine — required under research/prod (W34-F.4)

    def __post_init__(self) -> None:
        """Reject empty ``tenant_id`` under research/prod posture (W34-F.4).

        Mirrors the W34-F.3 ReasoningTrace pattern: spine fields raise on
        missing values when the platform is fail-closed, and degrade to a
        warning under dev for back-compat with legacy fixtures.
        """
        if self.tenant_id and self.tenant_id.strip():
            return
        posture = Posture.from_env()
        msg = (
            f"WikiPage(page_id={self.page_id!r}) constructed with empty "
            "tenant_id; cross-tenant attribution is forbidden under "
            "research/prod posture (W34-F.4)."
        )
        if posture.is_strict:
            raise ValueError(msg)
        logger.warning(msg)


class KnowledgeWiki:
    """File-based wiki for LLM-consumable knowledge.

    Structure (W34-F.4 tenant-partitioned layout):
      wiki_dir/
        index.md                 - top-level catalog (tenant-aware)
        log.md                   - append-only operation log
        <tenant_id>/             - per-tenant page directory
          <page_id>.json         - individual wiki pages

    Operations (from Karpathy pattern):
      - ingest: Process source -> extract entities/concepts -> create/update pages
      - query: Search pages -> return relevant knowledge with [[links]]
      - lint: Check for contradictions, orphan pages, stale claims

    Tenant scoping (W34-F.4 / B-W34-3):
      - ``add_page`` reads ``page.tenant_id`` off the dataclass.
      - ``get_page``, ``list_pages``, ``search`` require a ``tenant_id``
        keyword argument.
      - Under dev posture, missing ``tenant_id`` emits a warning and
        falls back to the sentinel ``"default"`` tenant.
      - Under research/prod posture, missing ``tenant_id`` raises
        ``ValueError`` (no silent cross-tenant reads).
    """

    def __init__(self, wiki_dir: str = ".hi_agent/knowledge/wiki") -> None:
        """Initialize KnowledgeWiki."""
        self._wiki_dir = Path(wiki_dir)
        # Per-tenant in-memory page store: tenant_id -> { page_id -> WikiPage }
        self._pages: dict[str, dict[str, WikiPage]] = {}

    # ------------------------------------------------------------------ Tenant resolution

    @staticmethod
    def _resolve_tenant_for_read(tenant_id: str | None, *, op: str) -> str:
        """Return the effective tenant id for a read call.

        Under dev posture, an empty/None ``tenant_id`` is replaced with
        ``"default"`` and a warning is logged. Under research/prod, an
        empty/None value raises ``ValueError`` so that cross-tenant reads
        cannot succeed silently.
        """
        if tenant_id and tenant_id.strip():
            return tenant_id
        posture = Posture.from_env()
        msg = (
            f"KnowledgeWiki.{op}: tenant_id is missing or empty; "
            "cross-tenant reads are forbidden under research/prod posture "
            "(W34-F.4)."
        )
        if posture.is_strict:
            raise ValueError(msg)
        logger.warning(msg)
        return _DEFAULT_TENANT

    @staticmethod
    def _resolve_tenant_for_write(tenant_id: str | None, *, op: str) -> str:
        """Return the effective tenant id for a write call.

        Same posture rules as :meth:`_resolve_tenant_for_read`: dev →
        warn + default; research/prod → raise.
        """
        if tenant_id and tenant_id.strip():
            return tenant_id
        posture = Posture.from_env()
        msg = (
            f"KnowledgeWiki.{op}: tenant_id is missing or empty; "
            "cross-tenant writes are forbidden under research/prod posture "
            "(W34-F.4)."
        )
        if posture.is_strict:
            raise ValueError(msg)
        logger.warning(msg)
        return _DEFAULT_TENANT

    def _bucket(self, tenant_id: str) -> dict[str, WikiPage]:
        """Return (creating if needed) the in-memory page bucket for one tenant."""
        bucket = self._pages.get(tenant_id)
        if bucket is None:
            bucket = {}
            self._pages[tenant_id] = bucket
        return bucket

    # ------------------------------------------------------------------ CRUD

    def add_page(self, page: WikiPage) -> None:
        """Add a wiki page. Sets timestamps if missing.

        The page's ``tenant_id`` is the source of truth. Under dev
        posture, an empty value is rewritten to ``"default"`` (with a
        warning). Under research/prod, ``WikiPage.__post_init__`` already
        rejected the empty value at construction time.
        """
        tenant_id = self._resolve_tenant_for_write(page.tenant_id, op="add_page")
        if not page.tenant_id:
            # Stamp the resolved tenant onto the dataclass so downstream
            # consumers (search results, persistence) see the same value.
            page.tenant_id = tenant_id

        now = datetime.now(UTC).isoformat()
        if not page.created_at:
            page.created_at = now
        if not page.updated_at:
            page.updated_at = now
        # Auto-extract outgoing links from content
        page.outgoing_links = self.extract_links(page.content)
        self._bucket(tenant_id)[page.page_id] = page

    def update_page(
        self,
        page_id: str,
        content: str | None = None,
        tags: list[str] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Update an existing page's content and/or tags within one tenant."""
        effective = self._resolve_tenant_for_write(tenant_id, op="update_page")
        bucket = self._pages.get(effective)
        if bucket is None:
            return
        page = bucket.get(page_id)
        if page is None:
            return
        if content is not None:
            page.content = content
            page.outgoing_links = self.extract_links(content)
        if tags is not None:
            page.tags = tags
        page.updated_at = datetime.now(UTC).isoformat()

    def get_page(
        self,
        page_id: str,
        *,
        tenant_id: str | None = None,
    ) -> WikiPage | None:
        """Get a page by ID within one tenant.

        Returns ``None`` when the page does not exist for the given
        tenant — this is the 404-shape defense against cross-tenant
        leakage. Tenant A reading a page belonging to tenant B sees a
        clean miss, not the page (B-W34-3 acceptance criterion).
        """
        effective = self._resolve_tenant_for_read(tenant_id, op="get_page")
        bucket = self._pages.get(effective)
        if bucket is None:
            return None
        return bucket.get(page_id)

    def remove_page(
        self,
        page_id: str,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Remove a page by ID within one tenant."""
        effective = self._resolve_tenant_for_write(tenant_id, op="remove_page")
        bucket = self._pages.get(effective)
        if bucket is None:
            return
        bucket.pop(page_id, None)

    def list_pages(
        self,
        page_type: str | None = None,
        *,
        tenant_id: str | None = None,
    ) -> list[WikiPage]:
        """List all pages for one tenant, optionally filtered by type."""
        effective = self._resolve_tenant_for_read(tenant_id, op="list_pages")
        bucket = self._pages.get(effective, {})
        pages = list(bucket.values())
        if page_type is not None:
            pages = [p for p in pages if p.page_type == page_type]
        return sorted(pages, key=lambda p: p.page_id)

    # ------------------------------------------------------------------ Search

    def search(
        self,
        query: str,
        limit: int = 10,
        *,
        tenant_id: str | None = None,
    ) -> list[WikiPage]:
        """Search by keyword match across one tenant's pages."""
        effective = self._resolve_tenant_for_read(tenant_id, op="search")
        if not query.strip():
            return []
        bucket = self._pages.get(effective, {})
        keywords = query.lower().split()
        scored: list[tuple[float, WikiPage]] = []
        for page in bucket.values():
            text = (page.title + " " + page.content + " " + " ".join(page.tags)).lower()
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                scored.append((hits, page))
        scored.sort(key=lambda pair: (-pair[0], pair[1].page_id))
        return [page for _, page in scored[:limit]]

    def get_linked_pages(
        self,
        page_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[WikiPage]:
        """Get all pages linked from the given page via [[wikilinks]] within one tenant."""
        effective = self._resolve_tenant_for_read(tenant_id, op="get_linked_pages")
        bucket = self._pages.get(effective, {})
        page = bucket.get(page_id)
        if page is None:
            return []
        result: list[WikiPage] = []
        for link_id in page.outgoing_links:
            linked = bucket.get(link_id)
            if linked is not None:
                result.append(linked)
        return result

    # ------------------------------------------------------------------ Wikilink resolution

    def resolve_links(
        self,
        content: str,
        *,
        tenant_id: str | None = None,
    ) -> str:
        """Replace [[page-id]] with page title for display, scoped to one tenant."""
        effective = self._resolve_tenant_for_read(tenant_id, op="resolve_links")
        bucket = self._pages.get(effective, {})

        def _replacer(match: re.Match[str]) -> str:
            pid = match.group(1)
            page = bucket.get(pid)
            if page is not None:
                return page.title
            return match.group(0)  # keep unresolved

        return _WIKILINK_RE.sub(_replacer, content)

    @staticmethod
    def extract_links(content: str) -> list[str]:
        """Extract all [[page-id]] references from content."""
        return _WIKILINK_RE.findall(content)

    # ------------------------------------------------------------------ Index & Log

    def rebuild_index(self, *, tenant_id: str | None = None) -> str:
        """Regenerate index.md for the given tenant and write it to disk."""
        effective = self._resolve_tenant_for_read(tenant_id, op="rebuild_index")
        bucket = self._pages.get(effective, {})
        lines = [f"# Knowledge Wiki Index — tenant {effective}", ""]
        for page in sorted(bucket.values(), key=lambda p: p.page_id):
            tags_str = ", ".join(page.tags) if page.tags else "none"
            lines.append(
                f"- **[{page.title}]({page.page_id}.md)** ({page.page_type}) - tags: {tags_str}"
            )
        lines.append("")
        index_content = "\n".join(lines)
        index_path = self._wiki_dir / effective / "index.md"
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
        """Append to log.md (shared across tenants for operational visibility)."""
        now = datetime.now(UTC).isoformat()
        log_path = self._wiki_dir / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"- [{now}] **{operation}**: {details}\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(entry)

    # ------------------------------------------------------------------ Lint

    def lint(self, *, tenant_id: str | None = None) -> list[str]:
        """Lint one tenant's pages and return orphan, broken-link, and stale issues."""
        effective = self._resolve_tenant_for_read(tenant_id, op="lint")
        bucket = self._pages.get(effective, {})
        issues: list[str] = []

        # Build incoming link map
        incoming: dict[str, int] = dict.fromkeys(bucket, 0)
        for page in bucket.values():
            for link_id in page.outgoing_links:
                if link_id in incoming:
                    incoming[link_id] += 1

        # Orphan pages (no incoming links, more than 1 page total)
        if len(bucket) > 1:
            for pid, count in sorted(incoming.items()):
                if count == 0:
                    issues.append(f"orphan: '{pid}' has no incoming links")

        # Broken links
        for page in bucket.values():
            for link_id in page.outgoing_links:
                if link_id not in bucket:
                    issues.append(
                        f"broken_link: '{page.page_id}' links to non-existent '{link_id}'"
                    )

        # Stale pages (updated_at older than 30 days)
        now = datetime.now(UTC)
        for page in bucket.values():
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
        """Write all pages to disk as JSON, partitioned by tenant.

        Layout: ``<wiki_dir>/<tenant_id>/<page_id>.json``. Tenants with
        no pages are not written.
        """
        for tenant_id, bucket in self._pages.items():
            tenant_dir = self._wiki_dir / tenant_id
            tenant_dir.mkdir(parents=True, exist_ok=True)
            for page in bucket.values():
                page_path = tenant_dir / f"{page.page_id}.json"
                page_path.write_text(
                    json.dumps(asdict(page), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            # Per-tenant index sits inside the tenant directory.
            index_path = tenant_dir / "index.md"
            index_path.write_text(
                self.rebuild_index(tenant_id=tenant_id), encoding="utf-8"
            )

    def load(self) -> None:
        """Load all pages from disk, restoring per-tenant partitions.

        Layout (current): ``<wiki_dir>/<tenant_id>/<page_id>.json``.
        Legacy layout (``<wiki_dir>/pages/<page_id>.json`` from before
        W34-F.4) is migrated lazily into the ``"default"`` tenant — those
        files are read and re-loaded under the default partition with a
        warning.
        """
        if not self._wiki_dir.exists():
            return
        self._pages.clear()

        # Discover tenant directories (skip the legacy "pages/" sibling).
        for entry in sorted(self._wiki_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name == "pages":
                self._load_legacy_pages(entry)
                continue
            tenant_id = entry.name
            for page_file in sorted(entry.glob("*.json")):
                page = self._read_page_file(page_file, tenant_id=tenant_id)
                if page is not None:
                    self._bucket(tenant_id)[page.page_id] = page

    def _load_legacy_pages(self, pages_dir: Path) -> None:
        """Migrate legacy ``pages/`` directory contents into the default tenant.

        W34-F.4 compatibility: pre-W34 deployments wrote a flat
        ``<wiki_dir>/pages/<page_id>.json`` layout with no tenant scope.
        We surface those into the ``"default"`` tenant so the data is
        still readable; a warning is logged so operators know to migrate.
        """
        if not pages_dir.exists():
            return
        files = list(pages_dir.glob("*.json"))
        if not files:
            return
        logger.warning(
            "KnowledgeWiki.load: legacy pages/ layout detected at %s — "
            "migrating %d files into the '%s' tenant; rerun save() to "
            "persist the new partitioned layout (W34-F.4).",
            pages_dir,
            len(files),
            _DEFAULT_TENANT,
        )
        for page_file in sorted(files):
            page = self._read_page_file(page_file, tenant_id=_DEFAULT_TENANT)
            if page is not None:
                self._bucket(_DEFAULT_TENANT)[page.page_id] = page

    def _read_page_file(self, page_file: Path, *, tenant_id: str) -> WikiPage | None:
        """Decode one page JSON file, stamping the resolved tenant when missing."""
        try:
            data = json.loads(page_file.read_text(encoding="utf-8"))
            stored_tenant = data.get("tenant_id", "") or tenant_id
            return WikiPage(
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
                tenant_id=stored_tenant,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "WikiStore.load: skipping corrupt page file %s: %s", page_file.name, exc
            )
            return None

    # ------------------------------------------------------------------ LLM-friendly output

    def to_context_string(
        self,
        page_ids: list[str],
        max_tokens: int = 2000,
        *,
        tenant_id: str | None = None,
    ) -> str:
        """Format selected pages as context for LLM injection (per-tenant)."""
        effective = self._resolve_tenant_for_read(tenant_id, op="to_context_string")
        bucket = self._pages.get(effective, {})
        parts: list[str] = []
        budget = max_tokens * 4  # rough chars-per-token estimate
        used = 0

        for pid in page_ids:
            page = bucket.get(pid)
            if page is None:
                continue
            section = f"## {page.title}\n{page.content}\n"
            if used + len(section) > budget:
                break
            parts.append(section)
            used += len(section)

        return "\n".join(parts) if parts else ""

    # ------------------------------------------------------------------ Internal helpers

    def _all_tenants(self) -> list[str]:
        """Return the list of tenants currently present in memory.

        ``# scope: process-internal`` — used by ``KnowledgeManager`` and
        ``RetrievalEngine`` when they need to walk the union of pages
        across tenants the manager already knows about. Callers MUST
        still scope their per-page reads through the public ``tenant_id``
        kwarg.
        """
        return sorted(self._pages.keys())


# Legacy compatibility — preserved so external code that touches the path
# constant (e.g. operator runbooks) still resolves.
_LEGACY_PAGES_DIR_NAME = "pages"
__all__ = ["KnowledgeWiki", "WikiPage"]

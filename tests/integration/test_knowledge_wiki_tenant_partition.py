"""Integration tests: KnowledgeWiki tenant partition (W34-F.4 / B-W34-3).

The wiki layer must structurally deny cross-tenant reads. After W34-F.4:

- Every ``WikiPage`` carries a ``tenant_id``; under research/prod posture
  ``__post_init__`` rejects an empty value.
- ``KnowledgeWiki.add_page`` reads ``page.tenant_id`` off the dataclass
  and partitions the in-memory and persistent storage per-tenant.
- ``get_page``, ``list_pages``, ``search`` all require a ``tenant_id``
  keyword argument; cross-tenant requests return ``None`` / empty lists
  (404-shape, not 403, not 200-with-foreign-data).
- Under dev posture, an omitted ``tenant_id`` falls back to the
  ``"default"`` tenant with a warning. Under research/prod, it raises
  ``ValueError``.

Layer 2 — Integration: real ``KnowledgeWiki`` with a tmp_path-backed
storage directory; tests exercise the public API exactly as
``KnowledgeManager`` does at runtime.
"""

from __future__ import annotations

import pytest
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wiki(tmp_path):
    """Fresh per-tenant KnowledgeWiki rooted at tmp_path."""
    return KnowledgeWiki(str(tmp_path / "wiki"))


def _make_page(*, page_id: str, tenant_id: str, content: str = "") -> WikiPage:
    return WikiPage(
        page_id=page_id,
        title=page_id.replace("-", " ").title(),
        content=content or f"Body of {page_id}.",
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Posture switching helper
# ---------------------------------------------------------------------------


@pytest.fixture()
def posture(monkeypatch, request):
    """Parametrize HI_AGENT_POSTURE (dev / research / prod)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", request.param)
    return request.param


# ---------------------------------------------------------------------------
# Core cross-tenant defense (per RIA §B-W34-3 acceptance, all 3 postures)
# ---------------------------------------------------------------------------


class TestCrossTenantPartition:
    """RIA §B-W34-3: tenant A reading tenant B's page must 404."""

    @pytest.mark.parametrize("posture", ["dev", "research", "prod"], indirect=True)
    def test_a_reads_own_entry(self, wiki: KnowledgeWiki, posture: str) -> None:
        """Tenant A writes E_A; tenant A reads E_A → success."""
        wiki.add_page(_make_page(page_id="E_A", tenant_id="tenant_A"))
        page = wiki.get_page("E_A", tenant_id="tenant_A")
        assert page is not None
        assert page.page_id == "E_A"
        assert page.tenant_id == "tenant_A"

    @pytest.mark.parametrize("posture", ["dev", "research", "prod"], indirect=True)
    def test_b_reads_own_entry(self, wiki: KnowledgeWiki, posture: str) -> None:
        """Tenant B writes E_B; tenant B reads E_B → success."""
        wiki.add_page(_make_page(page_id="E_B", tenant_id="tenant_B"))
        page = wiki.get_page("E_B", tenant_id="tenant_B")
        assert page is not None
        assert page.page_id == "E_B"
        assert page.tenant_id == "tenant_B"

    @pytest.mark.parametrize("posture", ["dev", "research", "prod"], indirect=True)
    def test_a_reads_b_entry_returns_none(
        self, wiki: KnowledgeWiki, posture: str
    ) -> None:
        """Tenant A reads E_B with A's tenant_id → None (404 shape, not 403, not the entry)."""
        wiki.add_page(_make_page(page_id="E_B", tenant_id="tenant_B"))
        # Tenant A asks for E_B with their own tenant_id; the wiki must
        # not return tenant B's page even though that page exists.
        result = wiki.get_page("E_B", tenant_id="tenant_A")
        assert result is None, (
            "Cross-tenant read returned tenant B's page to tenant A "
            "(W34-F.4 partition violation)."
        )

    @pytest.mark.parametrize("posture", ["dev", "research", "prod"], indirect=True)
    def test_b_reads_a_entry_returns_none(
        self, wiki: KnowledgeWiki, posture: str
    ) -> None:
        """Tenant B reads E_A with B's tenant_id → None."""
        wiki.add_page(_make_page(page_id="E_A", tenant_id="tenant_A"))
        result = wiki.get_page("E_A", tenant_id="tenant_B")
        assert result is None, (
            "Cross-tenant read returned tenant A's page to tenant B "
            "(W34-F.4 partition violation)."
        )

    @pytest.mark.parametrize("posture", ["dev", "research", "prod"], indirect=True)
    def test_list_pages_partitioned(
        self, wiki: KnowledgeWiki, posture: str
    ) -> None:
        """list_pages(tenant_id=A) returns only A's pages."""
        wiki.add_page(_make_page(page_id="E_A", tenant_id="tenant_A"))
        wiki.add_page(_make_page(page_id="E_B", tenant_id="tenant_B"))
        a_pages = wiki.list_pages(tenant_id="tenant_A")
        b_pages = wiki.list_pages(tenant_id="tenant_B")
        a_ids = {p.page_id for p in a_pages}
        b_ids = {p.page_id for p in b_pages}
        assert a_ids == {"E_A"}
        assert b_ids == {"E_B"}
        assert a_ids.isdisjoint(b_ids)

    @pytest.mark.parametrize("posture", ["dev", "research", "prod"], indirect=True)
    def test_search_partitioned(self, wiki: KnowledgeWiki, posture: str) -> None:
        """search(query, tenant_id=A) finds only A's pages."""
        wiki.add_page(
            _make_page(
                page_id="E_A", tenant_id="tenant_A", content="quarterly revenue review"
            )
        )
        wiki.add_page(
            _make_page(
                page_id="E_B", tenant_id="tenant_B", content="quarterly revenue review"
            )
        )
        a_hits = wiki.search("revenue", tenant_id="tenant_A")
        b_hits = wiki.search("revenue", tenant_id="tenant_B")
        assert {p.page_id for p in a_hits} == {"E_A"}
        assert {p.page_id for p in b_hits} == {"E_B"}


# ---------------------------------------------------------------------------
# Posture-aware missing-tenant_id behaviour
# ---------------------------------------------------------------------------


class TestPostureBehaviour:
    """Dev posture warns + falls back; research/prod raise."""

    def test_dev_missing_tenant_id_on_page_warns(
        self, wiki: KnowledgeWiki, monkeypatch, caplog
    ) -> None:
        """Under dev, ``WikiPage(tenant_id="")`` warns but does not raise."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        with caplog.at_level("WARNING"):
            page = WikiPage(page_id="E_X", title="X", content="x")
        # Construction succeeded.
        assert page.page_id == "E_X"
        # And a warning was emitted referencing W34-F.4.
        assert any("W34-F.4" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("strict_posture", ["research", "prod"])
    def test_strict_missing_tenant_id_on_page_raises(
        self, monkeypatch, strict_posture: str
    ) -> None:
        """Under research/prod, constructing a WikiPage with empty tenant_id raises."""
        monkeypatch.setenv("HI_AGENT_POSTURE", strict_posture)
        with pytest.raises(ValueError, match="tenant_id"):
            WikiPage(page_id="E_X", title="X", content="x")

    def test_dev_missing_tenant_id_on_get_falls_back_to_default(
        self, wiki: KnowledgeWiki, monkeypatch, caplog
    ) -> None:
        """Under dev, get_page() with no tenant_id reads the default partition."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        # Add a page with explicit tenant_id="default" — the bucket the
        # dev fallback uses.
        wiki.add_page(_make_page(page_id="E_DEFAULT", tenant_id="default"))
        with caplog.at_level("WARNING"):
            result = wiki.get_page("E_DEFAULT")  # no tenant_id kwarg
        assert result is not None
        assert any("tenant_id" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("strict_posture", ["research", "prod"])
    def test_strict_missing_tenant_id_on_get_raises(
        self, wiki: KnowledgeWiki, monkeypatch, strict_posture: str
    ) -> None:
        """Under research/prod, get_page() without tenant_id raises ValueError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", strict_posture)
        with pytest.raises(ValueError, match="tenant_id"):
            wiki.get_page("any_page")

    @pytest.mark.parametrize("strict_posture", ["research", "prod"])
    def test_strict_missing_tenant_id_on_search_raises(
        self, wiki: KnowledgeWiki, monkeypatch, strict_posture: str
    ) -> None:
        """Under research/prod, search() without tenant_id raises ValueError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", strict_posture)
        with pytest.raises(ValueError, match="tenant_id"):
            wiki.search("revenue")

    @pytest.mark.parametrize("strict_posture", ["research", "prod"])
    def test_strict_missing_tenant_id_on_list_raises(
        self, wiki: KnowledgeWiki, monkeypatch, strict_posture: str
    ) -> None:
        """Under research/prod, list_pages() without tenant_id raises ValueError."""
        monkeypatch.setenv("HI_AGENT_POSTURE", strict_posture)
        with pytest.raises(ValueError, match="tenant_id"):
            wiki.list_pages()


# ---------------------------------------------------------------------------
# Persistent layout — per-tenant directory partition
# ---------------------------------------------------------------------------


class TestPartitionedPersistence:
    """W34-F.4: storage layout is <wiki_dir>/<tenant_id>/<page_id>.json."""

    def test_save_creates_per_tenant_directories(
        self, tmp_path, monkeypatch
    ) -> None:
        """save() writes pages under <wiki_dir>/<tenant_id>/<page_id>.json."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        wiki_dir = tmp_path / "wiki"
        wiki = KnowledgeWiki(str(wiki_dir))
        wiki.add_page(_make_page(page_id="E_A", tenant_id="tenant_A"))
        wiki.add_page(_make_page(page_id="E_B", tenant_id="tenant_B"))
        wiki.save()
        # Tenant directories exist.
        assert (wiki_dir / "tenant_A" / "E_A.json").exists()
        assert (wiki_dir / "tenant_B" / "E_B.json").exists()
        # Cross-tenant files do NOT exist (the page is structurally
        # confined to its tenant directory).
        assert not (wiki_dir / "tenant_A" / "E_B.json").exists()
        assert not (wiki_dir / "tenant_B" / "E_A.json").exists()

    def test_load_restores_partitions(self, tmp_path, monkeypatch) -> None:
        """load() restores per-tenant partitions from on-disk layout."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        wiki_dir = tmp_path / "wiki"
        wiki = KnowledgeWiki(str(wiki_dir))
        wiki.add_page(_make_page(page_id="E_A", tenant_id="tenant_A"))
        wiki.add_page(_make_page(page_id="E_B", tenant_id="tenant_B"))
        wiki.save()
        # Fresh instance — load from disk and verify partition.
        wiki2 = KnowledgeWiki(str(wiki_dir))
        wiki2.load()
        assert wiki2.get_page("E_A", tenant_id="tenant_A") is not None
        assert wiki2.get_page("E_A", tenant_id="tenant_B") is None
        assert wiki2.get_page("E_B", tenant_id="tenant_B") is not None
        assert wiki2.get_page("E_B", tenant_id="tenant_A") is None

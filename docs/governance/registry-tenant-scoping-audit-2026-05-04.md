# W34-T-FOLLOWUP: Four-Registry Tenant-Scoping Audit (2026-05-04)

**Wave:** 34
**Date:** 2026-05-04
**Owner:** RO
**Closes (in part):** B-W34-4 (B-5 follow-through) per `docs/upstream-directives/hi-agent-wave34-engineering-expectations-2026-05-04.md` §B-W34-4
**Companion track:** B-W34-3 (`KnowledgeWiki` tenant partition) — closed by W34-F.4

---

## Audit table — six platform stores keyed by tenant

| Registry | Storage | tenant_id field | Schema NOT NULL | Read-path requires tenant_id | Cross-tenant integration test | Status at HEAD |
|---|---|---|---|---|---|---|
| KnowledgeWiki | JSON files (per-tenant directory layout) | YES (W34-F.4 — `WikiPage.tenant_id`) | N/A (file-based; per-tenant directory enforces partition structurally) | YES — `get_page` / `list_pages` / `search` / `update_page` / `remove_page` / `lint` / `rebuild_index` / `to_context_string` all require `tenant_id` kwarg under research/prod (W34-F.4) | `tests/integration/test_knowledge_wiki_tenant_partition.py` (30 tests × 3 postures) | CLOSED at W34-F.4 |
| KnowledgeGraph (`SqliteKnowledgeGraphBackend`) | SQLite | YES (`tenant_id` column) | YES — `PRIMARY KEY (id, tenant_id)` on `kg_nodes`; `PRIMARY KEY (src, dst, relation, tenant_id)` on `kg_edges` (`hi_agent/knowledge/sqlite_backend.py:44,54`) | YES — every query body uses `WHERE tenant_id = ?` | `tests/integration/test_kg_routes_tenant_isolation_e2e.py` and `test_kg_routes_tenant_scoped.py` | CLOSED (W31 §B-5) |
| SkillRegistry | JSON file (`hi_agent/skill/registry.py`) | YES — `ManagedSkill.tenant_id` (`hi_agent/skill/registry.py:55`); `SkillDefinition.tenant_id` (`hi_agent/skill/definition.py:184`); both raise on empty under research/prod | NOT enforced at the JSON-file layer (single shared file; no per-tenant directory) | YES at API layer — `SkillRegistry.get(skill_id, tenant_id=...)` filters by tenant under strict posture (`hi_agent/skill/registry.py:225`) | `tests/integration/test_skills_cross_tenant.py` — `xfail` with `expiry_wave="Wave 35"`; documents the JSON-file (schema-layer) gap | API-LAYER CLOSED; SCHEMA-LAYER OPEN (W35 carryover) |
| Tool registry | The hi-agent capability layer has no standalone "tool registry" module; tools are exposed through `hi_agent/capability/tools/` (a sub-package of `CapabilityRegistry`) and through `hi_agent/mcp/registry.py` (MCPServerEntry) | Capability-layer tools are tenant-agnostic by design (W31 T-6'); MCPServerEntry rows live in a per-process registry. | N/A | N/A — capabilities are platform-level metadata, not per-tenant data. Per-tenant *enablement* policy lives **above** this layer (in the route handler or operator policy). | N/A by design (capability layer); MCP registry is process-internal | TENANT-AGNOSTIC by design (closed by design — W31 T-6') |
| CapabilityRegistry | In-memory dict (`hi_agent/capability/registry.py:138`) | NO — explicitly tenant-agnostic (`# W31 T-6' decision: platform-level capability metadata; tenant-agnostic.`, line 73 + 122) | N/A | N/A | N/A — by design | TENANT-AGNOSTIC by design (closed by design — W31 T-6') |
| RunQueue | SQLite (`hi_agent/server/run_queue.py`) | YES | YES — `tenant_id TEXT NOT NULL` (line 142) | YES — 9 methods scope by `tenant_id` | `tests/integration/test_run_queue_tenant_defense_in_depth.py` (28 tests) | CLOSED at W33-D.2 |

---

## Conclusions

- **KnowledgeWiki:** closed in W34-F.4 (this wave). Persistent layout is now `<wiki_dir>/<tenant_id>/<page_id>.json`. Every public read/write requires a `tenant_id=` keyword argument under research/prod posture; dev posture warns and falls back to the `"default"` tenant for back-compat. The dataclass (`WikiPage`) carries `tenant_id` as a spine field with `__post_init__` validation. Cross-tenant `get_page`/`list_pages`/`search` returns `None` / empty list (404 shape) per RIA §B-W34-3 acceptance.
- **KnowledgeGraph:** confirmed closed at HEAD. PK includes `tenant_id`; every query body uses `WHERE tenant_id = ?`; integration evidence cited.
- **SkillRegistry:** API-layer enforcement present and fail-closed under strict posture; schema-layer enforcement (per-tenant JSON file or per-tenant directory) deferred to W35 per the existing `xfail` marker. Acceptable disposition under RIA Lens 1 since the API layer enforces today; W35 closes the structural gap (ledger entry P0-W31-skills-tenant).
- **Tool registry:** there is no dedicated "tool registry" in hi-agent. Tools are exposed via `hi_agent/capability/tools/` (sub-package of `CapabilityRegistry`) and via `hi_agent/mcp/registry.py`. Both surfaces are tenant-agnostic platform metadata by design (W31 T-6'). Per-tenant tool **enablement** is a policy concern that lives above this layer (route handler / operator policy), not a structural-partition concern.
- **CapabilityRegistry:** tenant-agnostic by design (W31 T-6'); structural enforcement is N/A. Per-tenant policy lives ABOVE this layer.
- **RunQueue:** confirmed closed at W33-D.2.

## RIA-side disposition

This audit answers B-W34-4. The only remaining tenant-scoping work post-W34 is the SkillRegistry schema-layer enforcement (xfail `Wave 35`). RIA can rely on API-layer scoping for the W34 timeframe; the schema-layer gap is documented, ledger-tracked, and bounded by an explicit expiry wave.

The W34 BLOCKER set does NOT need to grow to include any of the four registries: every one is either CLOSED at HEAD, CLOSED by W34-F.4 (this wave), or correctly classified as TENANT-AGNOSTIC BY DESIGN.

## Three-part closure for B-W34-3 (W34-F.4)

| Part | Evidence |
|---|---|
| (a) Code fix | `hi_agent/knowledge/wiki.py` (W34-F.4 commit) — `WikiPage.tenant_id` + `__post_init__`; `KnowledgeWiki` per-tenant in-memory partition + `<wiki_dir>/<tenant_id>/` storage; per-call `tenant_id` kwargs on every public read/write; legacy `pages/` directory migrated into the `default` tenant on `load()` |
| (b) Regression test + hard gate | Test: `tests/integration/test_knowledge_wiki_tenant_partition.py` (30 tests; 6 cross-tenant cases × 3 postures + 4 posture-behaviour cases + 2 persistence cases). Gate: `scripts/check_no_unscoped_knowledge_reads.py` AST-walks every `*.py` under `hi_agent/` and `agent_server/`; fails when a `KnowledgeWiki` read method is invoked without a `tenant_id=` kwarg. |
| (c) Delivery-process change | This audit document is the process artifact for B-W34-4; the new gate `scripts/check_no_unscoped_knowledge_reads.py` is the process artifact for B-W34-3 (it prevents future un-scoped read sites from landing). The audit table format becomes the template for any future "is registry X tenant-partitioned?" question. |

# docs — Map

> **Last refreshed:** 2026-05-06 (W35 corrective close + W36 plans). HEAD `276917d8`.
> **Audience:** anyone navigating this repo's documentation.

This directory is the documentation root. Documents are grouped by **purpose**, not chronology, even though file dates record when each artifact was written. The wave model below explains how new documents enter the tree.

---

## Top-level reference

| Path | Purpose |
|---|---|
| `architecture-reference.md` | Stable codebase facts shared across packages — symbols, file maps, module boundaries. The first place to look. |
| `platform-capability-matrix.md` | The single source of truth for capability L0–L4 status (Rule 13). |
| `platform-contract.md` | Northbound contract overview (links into `agent_server/contracts/`). |
| `platform-gaps.md` | Open downstream platform gaps (P-1..P-7) — Rule 10 enforcement. |
| `posture-reference.md` | `dev` / `research` / `prod` posture semantics (Rule 11). |
| `api-reference.md` | HTTP API reference (route inventory + idempotency contract). |
| `route-inventory.md` | Auto-generated route table (`scripts/generate_route_inventory.py`). |
| `recovery-state-machine.md` | RunActor + RecoveryGate state machine reference. |
| `extension-guide.md` | How third parties register/extend kernel capabilities (L4). |
| `integration-guide.md`, `quickstart-research-profile.md` | First-contact docs for downstream teams. |
| `secret-hygiene.md`, `api-key-source.md` | Secret-handling rules. |
| `operator-runbook.md` | Operator-facing runbook (canonical entry). |
| `clean-env-verification.md` | Default-offline clean-env runner reference (Rule 16). |
| `failure-attribution.md` | How failures are mapped to recovery / gate. |
| `capability-boundaries.md` | Three-gate demand-intake reference (CLAUDE.md operational appendix). |
| `current-wave.txt` | Plain-text current wave number — read by `scripts/check_wave_consistency.py`. |
| `TODO.md` | Tracked open work; cross-referenced by closure notices. |
| `rules-incident-log.md` | History of rule origins (R1–R17) + narrow-trigger detail. |
| `self-audit-playbook.md` | Self-audit method (Rule 9). |

---

## `governance/` — binding governance configs

These are NOT docs in the prose sense; they are **functional governance configs** read by CI gates. Modifying any file here is NOT a "docs-only" change under Rule 14.

| File | Purpose |
|---|---|
| `score_caps.yaml` | Cap rules — when each named cap factor fires and how much it caps `current_verified_readiness`. |
| `allowlists.yaml` | Tracked technical debt (Rule 17) — every entry carries owner / risk / reason / expiry_wave / replacement_test / added_at. |
| `recurrence-ledger.yaml` | Defects that re-appeared — closure-process change records per Rule 15 part 3. |
| `closure-taxonomy.md` | Rule 15 closure-claim enum reference (5 levels: `component_exists` → `operationally_observable`). |
| `evidence-provenance-schema.md` | Schema for `provenance: real|synthetic|deferred` on every evidence file. |
| `retention-roadmap.md` | 8-store retention adoption tracking (W36-A3 binding). |
| `boot-time-assertions-roadmap.md` | 22-gap boot-assertion tracking (W36-A5 binding covers B1–B14). |
| `orphan-gates-audit-2026-05-05.md` | W35-corrective audit of `scripts/check_*.py` CI coverage (now 100 % wired). |
| `systematic-audit-w35-2026-05-05.md` | The 91-finding hidden-defect audit; W35 closed 38, W36 scope = 32, W37+ = 17. |
| `release-captain-checklist.md` | Captain pre-release checklist. |
| `delivery-protocol.md` | Delivery protocol per CLAUDE.md Rule 14. |
| `maturity-glossary.md` | L0–L4 enum glossary (Rule 13). |
| `p-gap-vocabulary.md` | Downstream-defined P-N gap vocabulary (Rule 10). |
| `contract_v1_freeze.json` | Frozen byte-snapshot of `agent_server/contracts/v1/**`. |
| `current-wave.txt` | Wave number (must agree with top-level `current-wave.txt` per W17/B11). |
| `cleanup-audit-*.md`, `dead-code-audit-*.md`, `env-var-audit-*.md`, `package-consolidation-*.md`, `local-cleanup-*.md`, `registry-tenant-scoping-audit-*.md`, `wave-28-expiry-triage.md`, `errata/` | Audit + cleanup records by date. |

---

## `upstream-directives/` — RIA inputs (M2 maturity)

Directives mirrored from RIA (research intelligence app team). Each is the authoritative scope for the named wave.

| File | Wave |
|---|---|
| `2026-05-05-hi-agent-w35-corrective-directive.md` | W35 corrective |
| `2026-05-05-hi-agent-w35-acceptance-audit.md` | W35 acceptance |
| `2026-05-05-hi-agent-wave36-engineering-expectations.md` | W36 (current binding) |
| `hi-agent-wave34-engineering-expectations-2026-05-04.md` | W34 |

A directive arriving from RIA requires a written response under `downstream-responses/` (Rule 10).

---

## `downstream-responses/` — our delivery / corrective notices

Our outbound responses to RIA. Every closure notice MUST cite the manifest_id and use RIA's vocabulary (PI-A..PI-E impact, P-N gaps), not our internal labels (Rule 10).

Recent (W19+):

- `2026-05-05-w35-delivery-notice.md`
- `2026-05-05-w35-corrective-response.md`
- earlier waves under the same naming convention.

`scripts/check_downstream_response_format.py` validates the schema.

---

## `releases/` — manifests + signoffs

Per Rule 14, the manifest is the **single release fact source**. Closure notices derive their claims from it; they do not independently restate HEAD / scores / readiness.

| File | Role |
|---|---|
| `platform-release-manifest-<date>-<short_sha>.json` | Authoritative release manifest. Generated by `scripts/build_release_manifest.py`. |
| `wave<N>-signoff.json` | Release-captain signoff JSON. References manifest_id, evidence files, score caps. |
| `release-captains.md` | Captain rotation. |
| `archive/W<N>/` | Stale intermediate manifests moved here per W17/B19. |

Current (W35): manifest_id `2026-05-05-24cfa0a6` at release_head `24cfa0a67249d9824f9ecd39f60764a548fe2699`; `current_verified_readiness=75.0` (capped by `soak_evidence_not_real`); `wave35-signoff.json` is the captain-signed companion.

---

## `superpowers/plans/` — accepted wave plans

Wave-scoped engineering plans. The directory itself is git-ignored by default; specific plans are force-added when they become wave bindings.

W36 plans (force-added 2026-05-06):

- `2026-05-06-wave-36-a3-tier1-retention-adoption.md` — 8 SQLite stores adopt W35-T4 `purge_expired` shape.
- `2026-05-06-wave-36-a4-schema-lineage-extensions.md` — schema lineage extensions.
- `2026-05-06-wave-36-a5-boot-time-assertions.md` — B1–B14 boot assertions.

Older accepted plans remain for traceability (W30, W31, W32, W33, W34, W35).

---

## `verification/` — evidence artifacts

Evidence files keyed by `<short_sha>-<artifact-name>.json`. Each artifact has a sibling `*-provenance.json` per `evidence-provenance-schema.md`.

Common artifact types:

- `<sha>-default-offline-clean-env.json` — Rule 16 clean-env evidence.
- `<sha>-arch-7x24.json` — Rule 8 architectural-7×24 5-assertion evidence.
- `<sha>-observability-spine.json` — observability-spine completeness evidence.
- `<sha>-chaos-runtime.json` — chaos runtime-coupling evidence.
- `<sha>-manifest-gate.json` — manifest-freshness gate report.
- `<sha>-score-cap.json` — score-cap report.

---

## `delivery/` — T3 real-LLM evidence

Per-commit T3 evidence (Rule 8 step 3). Naming: `<date>-<short_sha>-t3-volces.json` (or `-rule15-volces.json` for older Rule-15 evidence runs); each pairs with `*-provenance.json`. Soak stdout is captured at `soak-run-stdout.log`. Older artifacts archived under `delivery/archive/`.

---

## `observability/` — operator-facing metric docs

| File | Purpose |
|---|---|
| `idempotency-metrics.md` | `hi_agent_idempotency_purged_total{tenant_id}` reference (W35-T4 baseline). |

W36-A3 retention metrics will land here per the plan.

---

## `runbooks/` — operator runbooks for cap rules

Each runbook covers a specific cap factor or operational anti-pattern.

| File | Cap / scenario |
|---|---|
| `manifest-stale.md` | Manifest is older than HEAD. |
| `clean-env-not-final-head.md` | Clean-env evidence not at release_head. |
| `chaos-no-runtime-coupling.md` | Chaos scenarios not runtime-coupled. |
| `observability-spine-structural.md` | Spine evidence has structural gaps. |
| `soak-evidence-stale.md` | Soak evidence past freshness window. |
| `cross-tenant-primitive-footgun.md` | Tenant-scope escape. |
| `ownership-accountability-weak.md` | Owner-tag missing or wrong. |
| `release-gate-weakening.md` | A gate switched from required to advisory without note. |
| `score-cap-overstates-readiness.md` | Score cap not firing when it should. |
| `secret-rotation.md` | Provider key rotation. |
| `test-theatre-passing-via-fallback.md` | Tests passing only because of silent degradation. |

`scripts/runbook_drill.py` exercises each runbook periodically.

---

## Other top-level subdirectories

| Path | Purpose |
|---|---|
| `architecture/` | Detailed architecture diagrams (per-subsystem). |
| `migration/`, `migration-guides/` | Schema + API migration guides. |
| `perf/` | Performance baselines. |
| `platform/` | Platform-layer reference docs. |
| `research/` | Research-team facing notes. |
| `runbook/` | Older runbook directory (being consolidated into `runbooks/`). |
| `specs/` | Long-form specifications. |
| `sprints/` | Per-sprint planning notes (older). |
| `superpowers/` | Wave plans (currently only `plans/` subdir is force-added). |

---

## Wave model (how docs enter the tree)

Each wave closes with a four-document cluster:

1. **Manifest** — `releases/platform-release-manifest-<date>-<short_sha>.json` (generated, not hand-edited).
2. **Signoff** — `releases/wave<N>-signoff.json` (release-captain JSON, references manifest).
3. **Delivery notice** — `downstream-responses/<date>-w<N>-delivery-notice.md` (uses RIA vocabulary; cites manifest_id).
4. **Corrective response (optional)** — `downstream-responses/<date>-w<N>-corrective-response.md` if RIA issued a corrective directive in the same wave.

Plus, when applicable:

- **Plan** — `superpowers/plans/<date>-wave-<N>-<topic>.md` (accepted scope).
- **Audit** — `governance/<topic>-audit-<date>.md` (one-off systematic audits).
- **Roadmap update** — `governance/<roadmap>.md` rows flipped to `closed @ <SHA>`.

The order is **mandatory** (Rule 14 §4.4): final implementation commit → gates → manifest → score cap → closure notice.

---

## Cross-references

- Engineering rules → `../CLAUDE.md`
- Governance scripts → `../scripts/README.md`
- Test profiles → `../tests/README.md`
- Architecture → `../ARCHITECTURE.md`, `../hi_agent/ARCHITECTURE.md`, `../agent_kernel/ARCHITECTURE.md`

To-confirm: this map reflects the directory listing at HEAD `276917d8`; new top-level subdirectories require an entry here on the next docs refresh.

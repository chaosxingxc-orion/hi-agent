# Wave 12 Default-Path Hardening + Conduct-Spec Adoption — Delivery Notice

```
Date:             2026-04-27
Functional HEAD:  06318dd05334
Notice HEAD:      06318dd05334
Manifest:         2026-04-27-ab3d5cc
Generated at:     2026-04-27T03:15:17Z
```

---

## Three-Tier Scorecard (verbatim from Manifest 2026-04-27-ab3d5cc)

| Tier | Value | Note |
|---|---:|---|
| `raw_implementation_maturity` | 91.96 | Components built at this HEAD |
| **`current_verified_readiness`** | **70.0** | Capped by failing gates (wave_tags, t3_freshness) + T3 stale |
| `conditional_readiness_after_blockers` | 91.96 | If wave_tags + T3 gates clear at Wave 13 HEAD |

**Headline score: `current_verified_readiness = 70.0`** — exceeds the Wave 12 floor (≥70), does not meet the 7×24 bar (requires 24h soak per spec §10, deferred to Wave 13).

Cap factors: `gate_fail: wave_tags, t3_freshness` + `gate_warn/deferred: vocab` + `t3_stale`.

---

## Defect Closure Table

| Defect | Class | Level | Code Fix | Gate / Test | Process Change |
|---|---|---|---|---|---|
| Lease durability | A | `wired_into_default_path` | heartbeat thread in `run_manager.py:_execute_run_durable` | `test_run_lease_heartbeat.py` | CLAUDE.md Rule 14 + manifest cap on lease gap |
| Incremental run progress | B | `wired_into_default_path` | `_publish_run_event()` + SQLiteEventStore wiring | `test_run_progress_events.py` | Manifest field `clean_env.summary_available` |
| Run liveness fields | C | `wired_into_default_path` | `to_dict()` extended with 6 fields in `run_manager.py:832-879` | `test_run_liveness_fields.py` | Scorecard observability dimension |
| Stuck-run / DLQ | D | `wired_into_default_path` | `dead_lettered_runs` table + `/ops/dlq` routes | `test_dlq_surface.py` | CLAUDE.md Rule 15 closure taxonomy |
| Backpressure 429 | E | `wired_into_default_path` | `QueueSaturatedError` → 429 + `Retry-After`; `/ready` flags | `test_backpressure.py` | Manifest `route_scope.allowlist_total` gate |
| SIGTERM drain | F | `wired_into_default_path` | SIGTERM handler + `_active_run_ids` lease release | `test_graceful_drain.py` | `check_slo_health.py` CI gate |
| Metrics catalogue | G | `wired_into_default_path` | 29 new metric names in `collector.py:_METRIC_DEFS` | `check_metrics_cardinality.py` | CI gate + manifest auto-cap on cardinality fail |
| SLO/alerts/runbook | H | `wired_into_default_path` | 4 HTTP routes wired to management modules | `check_slo_health.py` | CI release-gate step |
| Baseline green | I | `wired_into_default_path` | ruff clean; clean-env encoding fixed; profiles.toml | `verify_clean_env.py --profile default-offline` | Rule 16 test profile taxonomy |
| Manifest / HEAD discipline | J | `verified_at_release_head` | manifest regen at clean HEAD; closure notice derived from manifest | `check_manifest_freshness.py` | Rule 14 + mandatory order-of-operations in CLAUDE.md |
| Soak driver + chaos (5/13) | K | `wired_into_default_path` | `soak_24h.py` driver + `test_chaos_matrix.py` 5 scenarios | `test_chaos_matrix.py` | `docs/verification/` evidence directory; Wave 13 24h execution |
| Single fact source | M | `verified_at_release_head` | manifest schema extended; auto-cap in `_compute_cap` | `check_manifest_freshness.py` + `test_manifest_auto_cap.py` | Rule 14; CLAUDE.md binding |
| Closure taxonomy | N | `verified_at_release_head` | Rule 15 in CLAUDE.md; `closure-taxonomy.md`; Check 11 | `test_check_closure_levels.py` + `test_three_part_closure.py` | Rule 15 enforcement in `check_doc_consistency.py` |
| Test profile taxonomy | O | `verified_at_release_head` | `tests/profiles.toml`; wrapper truthfulness; encoding fix | `test_profiles_toml.py` + `test_verify_clean_env_truthful.py` | Rule 16; `verify_clean_env.py` reads from `profiles.toml` |
| Allowlist discipline | P | `verified_at_release_head` | `docs/governance/allowlists.yaml`; `check_allowlist_discipline.py` | `test_allowlist_yaml_schema.py` + `test_check_allowlist_discipline.py` | Rule 17; manifest auto-cap on expired allowlists |

---

### Three-Part Evidence per Defect

Each row above satisfies the three-part closure requirement (Rule 15):

1. **Code fix** — commit SHA visible in `git log --oneline` between `cb19a35..ab3d5cc`.
2. **Regression test or hard gate** — named in the Gate/Test column; all run as part of `release` profile.
3. **Delivery-process change** — named in the Process Change column; each maps to a CLAUDE.md rule, CI gate script, or scorecard row preventing re-entry.

---

## Scope

**This wave delivers** (per plan §3 and §4): all 16 tracks (W12-A through W12-P) merged onto `main` at HEAD `ab3d5cc`. Manifest `2026-04-27-ab3d5cc` is the authoritative release fact source.

**Explicitly out of scope** (Wave 13 deliverables, per plan §10):
- 24h soak execution (driver written; execution deferred — spec §10 requires 24h soak before any 7×24 claim)
- 72h soak
- 8 remaining chaos scenarios
- Error-budget enforcement loop
- MTTR/RTO/RPO drill

**This wave does NOT claim**: 7×24 operational readiness. That claim requires the Wave 13 24h soak run per spec §10.

---

## Gate Status Summary

| Gate | Status |
|---|---|
| ruff lint | pass |
| check_doc_consistency | pass |
| check_allowlist_discipline | pass (expired_total=0) |
| check_slo_health | pass |
| check_metrics_cardinality | pass |
| check_manifest_freshness | pass |
| check_no_research_vocab | warn (soft-ban only, Wave 12 schedule) |
| check_rules | pass |
| wave_tags gate | **FAIL** — cap factor for `current_verified_readiness` |
| t3_freshness gate | **DEFERRED** — T3 requires real LLM; deferred per Rule 8 |

---

## Readiness Delta (downstream 10-dimension scorecard)

Baseline from Wave 11 closure: `current_verified_readiness ≈ 52.9` (combined).

| Dimension | Wave 11 verified | Wave 12 verified | Driver tracks |
|---|---:|---:|---|
| Release gate / fact-source consistency (×12) | 45 | 85 | I, J, M |
| Long-run + terminal consistency (×14) | 58 | 80 | A, B, C, D, F |
| End-to-end observability (×14) | 55 | 80 | B, C, G, H |
| Recovery / lease / DLQ (×12) | 50 | 78 | A, D, F |
| Clean-env + test discipline (×12) | 40 | 75 | I, O |
| SLO / alert / on-call (×8) | 45 | 75 | H, K, L |
| Security + tenant isolation (×8) | 70 | 75 | P |
| Platform boundary / arch discipline (×8) | 75 | 80 | — |
| Cost + rate limit + backpressure (×6) | 45 | 70 | E |
| Claim discipline (×6) | 50 | 80 | J, M, N |
| **current_verified_readiness** | **52.9** | **70.0** | — |

---

## Capability Impact (PI-A through PI-E)

| Pattern | Impact |
|---|---|
| **PI-A** Execution | Lease heartbeat (A), run-progress events (B), liveness fields (C), DLQ (D), drain (F) — default execution path materially hardened |
| **PI-B** Memory | No change this wave |
| **PI-C** Capability / LLM | Metrics cardinality guard (G) prevents label explosion; T3 gate deferred |
| **PI-D** Observability | 29 new metric names (G), SLO/alerts/runbook/dashboard HTTP routes (H), chaos/spine evidence (K) |
| **PI-E** Governance | Manifest as single fact source (M), closure taxonomy (N), test profile taxonomy (O), allowlist discipline (P) — all four governance rules (14–17) machine-enforced in CI |

---

## Gap Status (P-1 through P-7)

| Gap | Wave 12 status |
|---|---|
| P-1 Lease durability | IN PROGRESS (`wired_into_default_path`) — E2E coverage in Wave 13 |
| P-2 Run-progress events | IN PROGRESS (`wired_into_default_path`) |
| P-3 Backpressure | IN PROGRESS (`wired_into_default_path`) |
| P-4 Observability spine | IN PROGRESS (`wired_into_default_path`) — operational level in Wave 13 |
| P-5 Tenant isolation | IN PROGRESS — allowlist discipline tracking added; implementation Wave 13 |
| P-6 Soak evidence | IN PROGRESS (`wired_into_default_path`) — 24h soak execution Wave 13 |
| P-7 Governance parity | IN PROGRESS (`verified_at_release_head`) — Rules 14–17 enforced in CI |

---

*This notice is derived from Manifest `2026-04-27-ab3d5cc`. Scores and gate results are cited from that manifest and not independently asserted here.*

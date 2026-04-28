# Wave 18 ！ Vocabulary Debt Clearance + Stable 80 Baseline

## Delivery Notice

```
Functional HEAD:    ed69a62
Manifest:           2026-04-28-ed69a62
T3 evidence:        docs/delivery/2026-04-29-9ed019c-t3-volces.json (3 Volces runs, real LLM, provenance=real)
Clean-env evidence: docs/verification/1d78056-default-offline-clean-env.json (8707 passed, 0 failed)
Current verified readiness: 80.0 (gate_warn/deferred: pytest_skip_discipline, multistatus_gates, observability_spine_completeness, soak_evidence)
Validated by:       scripts/build_release_manifest.py scripts/check_allowlist_discipline.py scripts/check_no_research_vocab.py
Status:             current
```

---

## Scope

Wave 18 clears vocabulary debt (C4), stabilizes the 80.0 verified readiness baseline, and delivers fresh T3 + clean-env evidence at the functional HEAD. C1 (governance erosion) and C2 (evidence fakery) are deferred to Wave 19 with updated ledger entries.

Target: hold verified readiness at `80.0` with 0 expired allowlist entries and no head_mismatch.

---

## Class-Level Closure Map

| Class | Mechanism Fixed | Instances Closed | CI Gate Preventing Reentry |
|---|---|---|---|
| C4 ！ Vocabulary debt | 7 allowlist entries cleared; `apply_research_defaults` callsites removed; aliases deleted in `evolve/contracts.py`, `artifacts/contracts.py`, `llm/tier_presets.py`, `llm/__init__.py` | 7 expired Wave-17 allowlist entries ★ 0 | `check_no_research_vocab.py`, `check_allowlist_discipline.py` |
| C3 ！ Release identity | Manifest regenerated at functional HEAD; head_mismatch resolved; T3 + clean-env evidence at same HEAD | Prior manifest was 20 commits stale (3d46066 vs ed69a62) | `check_manifest_freshness.py`, `check_wave_consistency.py` |

---

## Score Movement

| Tier | Wave 17 baseline | Wave 18 | Cap Factor |
|---|---|---|---|
| `current_verified_readiness` | 80.0 (stale manifest; 7 expiring allowlists) | 80.0 | gate_warn/deferred: 4 gates |
| `raw_implementation_maturity` | 81.25 | 81.25 | ！ |
| `seven_by_twenty_four_operational_readiness` | 65.0 | 65.0 | soak_24h deferred |
| `conditional_readiness_after_blockers` | 80.0 | 80.0 | C1/C2 pending |

Note: Verified stays at 80.0 not because nothing improved, but because the remaining 4 deferred gates (soak, spine completeness, skip discipline, multistatus) were already the binding caps in Wave 17. Wave 18 cleared the RISK factors (expired allowlists would have capped to ~63; chaos gate now passes). Wave 19 targets +6 via C1/C2 execution.

---

## Deferred-With-Cap (Honest)

| Item | Status | Cap | Why Deferred |
|---|---|---|---|
| C1 ！ Gate strictness audit | deferred to Wave 19 | ！ | Removing `continue-on-error` from release-gate.yml requires paired gate tests |
| C2 ！ Evidence driver rewrite | deferred to Wave 19 | ！ | `/ops/drain` endpoint and observation functions require C8/C9 spine work |
| pytest_skip_discipline | deferred | legacy | 150+ skips without expiry_wave; migration pending |
| multistatus_gates | deferred | adoption | multi-status conversion ongoing |
| observability_spine_completeness | deferred | structural | real spine needs live LLM trace |
| soak_evidence | deferred | 7x24=65 | 24h soak requires long-lived process |

---

## Evidence Index (at ed69a62)

- `docs/releases/2026-04-28-ed69a62.json` ！ release manifest
- `docs/delivery/2026-04-29-9ed019c-t3-volces.json` ！ T3 evidence (3 Volces runs, real LLM)
- `docs/verification/ed69a62-default-offline-clean-env.json` ！ clean-env evidence
- `docs/verification/ed69a62-observability-spine.json` ！ spine evidence (structural)


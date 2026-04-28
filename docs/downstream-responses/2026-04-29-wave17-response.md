# Wave 17 Delivery Notice Response

**Response date:** 2026-04-29
**Responding to:** `docs/downstream-responses/2026-04-28-wave17-delivery-notice.md`
**Head at response:** see current manifest

---

## Summary

Wave 17 closed at `verified=80.0` with 7 expired vocab allowlist entries and 5 deferred gates
contributing score caps. The platform team acknowledges the following:

### What Wave 17 delivered

- **B-series governance hardening** (W17-B11–B19): manifest rewrite budget gate, captain-checklist
  protocol, wave consistency gate, delivery-protocol docs, 3-file self-test harness, BLOCKER unit
  tests, smoke-test artifact archival.
- **Ledger maturity**: recurrence-ledger expanded with closure taxonomy; W17-A/B/C entries tracked.

### Known gaps at Wave 17 closure

| Gap | Root cause | Target wave |
|-----|-----------|-------------|
| 7 expired vocab allowlist entries | Aliases not deleted atomically | Wave 18 C4 (DONE) |
| `continue-on-error: true` on spine/soak/chaos CI gates | Gate weakening to keep CI green | Wave 18 C1 (DONE) |
| `provenance="real"` hard-coded in evidence drivers | Driver lied about observation | Wave 18 C2 (DONE) |
| Spine evidence 10/14 layers (4 C8 layers missing) | Events not wired (LLM/tool/heartbeat/trace) | Wave 20 C8 |
| 24h soak not run | soak_24h.py sampler bug + no drain endpoint | Wave 20 C9 |
| `check_gate_strictness.py` referenced in ledger but absent | Fictional closure in ledger | Wave 18 C1 (DONE) |

### Wave 17 ledger audit findings (W17-A honest status)

W17-A (`continue-on-error` removal) was NOT completed in Wave 17 despite the ledger claiming
`code_fix: commit`. The `continue-on-error: true` lines remained in `release-gate.yml` at push
time. This was corrected in Wave 18 C1 with honest ledger annotation.

---

## Readiness delta (7-dimension downstream scorecard)

| Dimension | Wave 17 | Wave 18 | Delta |
|-----------|---------|---------|-------|
| Execution | L3 | L3 | 0 |
| Memory | L2 | L2 | 0 |
| Capability | L2 | L2 | 0 |
| Knowledge Graph | L2 | L2 | 0 |
| Planning | L1 | L1 | 0 |
| Artifact | L3 | L3 | 0 |
| Evolution | L1 | L1 | 0 |

Wave 18 improves **governance integrity** (C1–C4) rather than capability level. The
`verified_readiness` score increase comes from removing score caps:
- Expired allowlist cap removed (C4)
- Gate strictness violations removed (C1)

---

## Next commitments

- Wave 19: Test honesty (C5/C6), doc truth gate, ledger schema
- Wave 20: Real 12-event spine (C8), 24h soak with SIGTERM (C9)

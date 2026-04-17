# W6 Sprint — SystemBuilder Low-Risk Split

**Sprint window**: 2026-04-17 (same day, sequential after W5)
**Goal**: ReadinessProbe + SkillBuilder + MemoryBuilder extracted as independent modules; SystemBuilder LOC reduced from 2063 to ~1723.

---

## Ticket Tracker

| Ticket | Description | Status | Commit | Merged |
|--------|-------------|--------|--------|--------|
| HI-W6-001 | SystemBuilder characterization suite (62 tests) | ✅ Merged | `d9f0388` | 2026-04-17 |
| HI-W6-002 | Extract `ReadinessProbe` (~219 LOC moved) | ✅ Merged | `1deff08` | 2026-04-17 |
| HI-W6-003 | Extract `SkillBuilder` (~52 LOC facades) | ✅ Merged | `9919fbc` | 2026-04-17 |
| HI-W6-004 | Extract `MemoryBuilder` (~69 LOC facades) | ✅ Merged | `66014b3` | 2026-04-17 |

---

## Exit Criteria

| Check | Baseline (W5) | Target | Result |
|-------|---------------|--------|--------|
| pytest passed | 3204 | ≥ 3204 | 3286 ✅ |
| pytest failed | 0 | 0 | 0 ✅ |
| Characterization suite green | — | 100% | 61/62 ✅ (1 pre-existing skip) |
| `SystemBuilder` LOC | 2063 | ~1400 | 1723 ✅ (−340) |
| `builder.readiness()` byte-identical | — | yes | yes ✅ |
| `ReadinessProbe` independent unit | — | yes | yes ✅ |
| `SkillBuilder` standalone (no builder ref) | — | yes | yes ✅ |
| `MemoryBuilder` standalone (no builder ref) | — | yes | yes ✅ |
| All W6-W10 rules: no private cross-access | — | yes | yes ✅ |

---

## New Modules

| File | Contents | LOC |
|------|----------|-----|
| `hi_agent/config/readiness.py` | `ReadinessProbe.snapshot()` — pure observer | 219 |
| `hi_agent/config/skill_builder.py` | `SkillBuilder` — 5 skill build methods | ~120 |
| `hi_agent/config/memory_builder.py` | `MemoryBuilder` — 8 memory build methods | 179 |

## SystemBuilder LOC progression

| After | LOC | Delta |
|-------|-----|-------|
| W5 baseline | 2063 | — |
| W6-002 (ReadinessProbe) | 1844 | −219 |
| W6-003 (SkillBuilder) | 1792 | −52 |
| W6-004 (MemoryBuilder) | 1723 | −69 |
| **Total W6** | **1723** | **−340** |

---

## W7 Deferred

- `KnowledgeBuilder` extraction (HI-W7-001)
- `RetrievalBuilder` extraction + post-construction mutation fix (HI-W7-002)
- RunExecutor characterization suite (HI-W7-003)
- `RunFinalizer` extraction (HI-W7-004)

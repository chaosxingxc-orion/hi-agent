# Wave 36 S-1 — 6h Linux Soak Plan

**Date:** 2026-05-07
**Reissued:** 2026-05-07 (S-1 amendment) — three RIA-required changes per `docs/upstream-directives/2026-05-07-hi-agent-w36-supplement-acceptance-and-s1-amendment.md` §2: (A-S-1-1) M=5→M=1 honest deviation marker; (A-S-1-2) reject 4h fallback pre-authorization; (A-S-1-3) `-soak-240m.json` → `-soak-6h.json` filename realignment.
**Wave:** W36 supplement (binding once amendment lands)
**Reference:** RIA W36 supplement directive §2.1 (`hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md`); RIA S-1 amendment (`hi-agent-w36-supplement-acceptance-and-s1-amendment-2026-05-07.md`); W34-LINUX-SOAK-ROADMAP (`docs/downstream-responses/2026-05-05-w34-delivery-notice.md:140-146`); CLAUDE.md Rule 8 §architectural 7×24
**Owner:** TE (track lead) + GOV (CI workflow) + DX (env-var convention)

> **Last refreshed:** 2026-05-07 (reissue). HEAD `7ee6acaa`.

---

## 1. Purpose & Reaffirmed Position

This plan supplements W36 with the 6h Linux soak the W34 roadmap committed to and the W36 entry directive named binding. It does not introduce new scope; it lands the artifact at the maturity level RIA's supplement ask requires.

The framing is RIA's reaffirmed Lens 7: **the soak measures architectural feasibility, not capacity.** Per the directive, both a clean 6h pass and a 6h pass that surfaces an architectural defect are successful W36 deliverables. This plan is **not tuned for cap retirement.** The `soak_evidence_not_real` cap (cap=75; `docs/governance/score_caps.yaml:173-178`) stays, retires, or reframes only as a function of measured outcome — driven by data, not by a target.

The plan also covers the two OS-limited chaos scenarios (`signal_storm`, `fd_exhaustion_recovery`) that the W34 roadmap noted as `runtime_partial` on Windows and named as W36 promotions to `real` on Linux. These are POSIX-only scenario *concepts* (SIGUSR1/SIGUSR2 multiplexing; `RLIMIT_NOFILE` manipulation) currently absent from `tests/chaos/scenarios/`; this plan makes their authoring + Linux-runner promotion the second deliverable.

## 2. Workload Specification

| Field | Value | Source |
|---|---|---|
| Runner | `ubuntu-latest` (4 vCPU / 16 GB RAM) | W34 roadmap §145 |
| Tenants (`--tenants`) | `50` | RIA §2.1 (workload N=50) |
| Projects per tenant (`--projects-per-tenant`) | `1` — **RIA-approved deviation** per `docs/upstream-directives/2026-05-07-hi-agent-w36-supplement-acceptance-and-s1-amendment.md` §2.1: workload runs at `--projects-per-tenant 1` (50 pairs) rather than the directive's literal 50×5=250; rationale is concurrency-saturation equivalence under runner constraint. M-equivalent (concurrency-saturation derived) reported separately, not as identity. | `scripts/run_soak.py:1029-1036` round-robin pair logic |
| Concurrency (`--concurrency`) | `50` | RIA §2.1 (N=50 concurrent) |
| Run interval (`--run-interval-seconds`) | `30.0` (chaos cadence) | RIA §2.1 (30s chaos cadence) |
| Duration (`--duration`) | `6h` | RIA §2.1 + W34 roadmap |
| Provenance gate | `real` per `_classify_provenance` band `>=14400 AND invariants_held → real (240m)` (`scripts/run_soak.py:689-696`) | upstream contract |
| Polling-mode | `--require-polling-observation` (Rule 8 step-5 strict mirror) | `scripts/run_soak.py:865-876` |
| Mid-soak SIGTERM | `--mid-soak-sigterm-after 180.0` (3h mark) | extends W31-L1 pattern; surfaces lease/recovery interaction at half-time |
| Sample interval (`--sample-interval-seconds`) | `30.0` | run_soak default |
| Per-run timeout | `180.0` (default) | `scripts/run_soak.py:923-928` |

The harness supports every field above; one minor `_evidence_filename` branch is required by RIA amendment §2.3 (filename realignment). The 6h primary band emits `<sha>-soak-6h.json`; the 4h fallback band continues to emit `<sha>-soak-240m.json` (RIA-decided rename per `docs/upstream-directives/2026-05-07-hi-agent-w36-supplement-acceptance-and-s1-amendment.md` §2.3 — name-and-content alignment so a 6h run is filed under a band that matches its duration). The evidence file we commit at W36 head is `docs/verification/<W36-head>-soak-6h.json`. The single-line change in `_evidence_filename` is named in §5 below; CI workflow + `check_soak_evidence.py` extension match the naming.

## 3. Chaos Scenarios — `runtime_partial` → `real` Promotion

The W34 roadmap names two POSIX-only scenarios as the source of `runtime_partial` provenance in `arch-7x24` evidence today (`docs/downstream-responses/2026-05-05-w34-delivery-notice.md:142`). Inspection at HEAD `975b7911` shows the scenario files do **not yet exist** in `tests/chaos/scenarios/` (only the 10 numbered scenarios `01_…` through `10_…`). Promotion to `real` therefore requires (a) authoring the two missing scenarios on a POSIX-only path, and (b) running them on `ubuntu-latest` so `run_chaos_runtime_coupled.py` reports `provenance: runtime` (not `runtime_partial` — see `scripts/run_chaos_runtime_coupled.py:521-530`).

### 3.1 `signal_storm`

- **Concept:** POSIX SIGUSR1/SIGUSR2 multiplexing — drive a burst of competing user-defined signals at the long-lived `python -m hi_agent serve` subprocess and assert that lifecycle, run-store invariants, and watchdog state all survive without corrupted state. Mirrors the lease-stall pattern in `tests/chaos/scenarios/08_lease_heartbeat_stall.py` but exercises signal-handler reentrancy rather than heartbeat backlog.
- **Current site:** absent. Add `tests/chaos/scenarios/11_signal_storm_posix.py`.
- **What blocks `real` provenance today:** the scenario does not exist. On Windows, `signal.SIGUSR1` is not defined, so the scenario must be guarded by `pytest.mark.skipif(sys.platform == "win32", ...)` and skip cleanly (`runtime_partial`) under the existing `run_chaos_runtime_coupled.py` driver.
- **What unblocks `real`:** authoring on Linux + a CI matrix shard that runs `run_chaos_runtime_coupled.py` on `ubuntu-latest` so all 11 scenarios execute. Once the new scenario reaches `executed=11, failed=0, skipped=0`, the driver emits `provenance: runtime` per the branch at `scripts/run_chaos_runtime_coupled.py:521-524`. (To-confirm: whether the RIA-binding count is "10 chaos scenarios" or "all chaos scenarios"; `score_caps.yaml::chaos_runtime_coupled_all` and `arch-7x24`'s 5th assertion both phrase as "all", so adding scenarios is non-breaking.)

### 3.2 `fd_exhaustion_recovery`

- **Concept:** POSIX `RLIMIT_NOFILE` manipulation — drop the running server's nofile rlimit, force the kernel-event-log + idempotency-store paths to hit `OSError: [Errno 24]`, then assert recovery (the silent-degradation counter increments, the run completes via the recovery path, and the rlimit raise restores normal operation). Mirrors the disk-full pattern in `tests/chaos/scenarios/07_disk_full_artifact_write.py` but exercises FD-limit pressure.
- **Current site:** absent. Add `tests/chaos/scenarios/12_fd_exhaustion_recovery_posix.py`.
- **What blocks `real` provenance today:** the scenario does not exist. On Windows, `resource.setrlimit(resource.RLIMIT_NOFILE, …)` is unavailable; same `skipif` guard.
- **What unblocks `real`:** authoring on Linux + the same CI matrix shard. Acceptance is identical to §3.1.

Both scenario files MUST register a `runtime_coupled: true` field in their evidence emission so `check_chaos_runtime_coupling.py` accepts them. Both MUST emit `provenance: real` when run on a live subprocess (the `_helpers.py` shared utilities already shape this).

## 4. Evidence Shape

### 4.1 Soak evidence file: `docs/verification/<W36-head>-soak-6h.json` (primary 6h band)

The 4h fallback band — only reachable after RIA-explicit approval per §10 Risk-1 — uses `docs/verification/<W36-head>-soak-240m.json` with `requested_duration_label: "4h"`. The two filenames are content-aligned: `-soak-6h.json` MUST carry `requested_duration_seconds: 21600`; `-soak-240m.json` MUST carry `requested_duration_seconds: 14400`. `check_soak_evidence.py` enforces the cross-check.

**Primary 6h band shape (this is the W36-S-1 closure target):**

Shape is dictated by `_write_evidence` at `scripts/run_soak.py:726-817` and is unchanged. Required top-level fields after a real 6h pass:

- `release_head`, `verified_head`, `check: "soak_evidence"`, `provenance: "real"`
- `requested_duration_label: "6h"`, `requested_duration_seconds: 21600`
- `duration_seconds >= 21600`, `invariants_held: true`
- `runs_submitted >= 360` (50 concurrency × 6h × ~12 runs/h floor — to-confirm against actual saturation)
- `lost_runs == 0`, `duplicate_run_ids == 0`, `llm_fallback_count == 0`
- `per_tenant: {…}` (multi-tenant mode auto-engages when `--tenants > 1`)
- `cross_tenant_leaks: []`
- `sigterm_events: [{…one entry…}]` (mid-soak SIGTERM at 3h)
- `in_flight_at_restart_count >= 1`, `resumed_after_restart_count >= 1`

A run that does NOT hold invariants is still a valid deliverable per Lens 7, but the evidence file then carries `provenance: shape_1h` (the harness will not classify a duration-met-but-invariant-failed run as `real`; see `_classify_provenance` at `scripts/run_soak.py:674-696`). Cap disposition §6 below covers that branch.

### 4.2 arch-7×24 re-run: `docs/verification/<W36-head>-arch-7x24.json`

Re-run `python scripts/run_arch_7x24.py` at the same HEAD as the soak. The 5/5 PASS contract from `scripts/check_soak_evidence.py:40-46` must hold. The fifth assertion (`chaos_runtime_coupled_all`) is the one promoted by §3 — once the two new scenarios land and `run_chaos_runtime_coupled.py` emits `provenance: runtime`, the assertion's existing path (`scripts/run_arch_7x24.py` lines below 80) flips from `runtime_partial`-tolerant to `runtime`-strict in the W37 cycle (out of scope for S-1 itself).

### 4.3 Delivery-notice template extension

The W36 delivery notice gains a "Linux soak" section that names the soak SHA, the workload row, and the cap disposition. One- or two-line addendum:

```
### W36-S-1 closure (three-part)
(a) Plan + workflow: docs/superpowers/plans/2026-05-07-wave-36-linux-soak.md ;
    .github/workflows/wave36-linux-soak.yml @ <SHA>
(b) Recurrence-prevention check: scripts/check_soak_evidence.py asserts
    provenance==real AND duration_seconds >= 21600 (extension under §7 below)
(c) Process change: CLAUDE.md Rule 8 §architectural 7×24 retains the 5
    static assertions; the wall-clock soak is now a separately-tracked
    measurement opportunity per RIA Lens 7.
```

## 5. CI Workflow Sketch

A new file `.github/workflows/wave36-linux-soak.yml` is the simplest landing — extending `release-gate.yml` would cross job-timeout boundaries (the release gate completes in single-digit minutes; a 6h job belongs in a separate workflow with its own concurrency group).

```yaml
name: Wave 36 Linux Soak (6h)
on:
  workflow_dispatch:        # operator-triggered
  schedule:
    - cron: "0 22 * * 5"    # weekly Fri 22:00 UTC overnight slot
permissions:
  contents: write           # for committing evidence at run HEAD
jobs:
  soak-6h:
    runs-on: ubuntu-latest
    timeout-minutes: 420    # 6h + 30 min buffer
    concurrency:
      group: wave36-linux-soak
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -e ".[dev]"
      - name: Run 6h soak
        run: |
          python scripts/run_soak.py \
            --duration 6h --port 9083 \
            --tenants 50 --projects-per-tenant 1 --concurrency 50 \
            --run-interval-seconds 30 \
            --mid-soak-sigterm-after 180 \
            --require-polling-observation
      - name: Re-run arch-7×24 at soak HEAD
        run: python scripts/run_arch_7x24.py
      - name: Validate soak evidence
        run: python scripts/check_soak_evidence.py --json --strict
      - uses: actions/upload-artifact@v4
        with:
          name: linux-soak-evidence
          path: docs/verification/*-soak-240m.json
```

The workflow is `workflow_dispatch` + `schedule`-driven, never on PR. It uploads evidence as an artifact; the operator commits the evidence + arch-7×24 file at the soak HEAD before publishing the W36 closure notice.

## 6. Cap Disposition Rule

**Not tuned for cap retirement.** Three measured outcomes drive three dispositions for `soak_evidence_not_real` (cap=75):

1. **Clean 6h pass** (`provenance: real`, `invariants_held: true`, `duration_seconds >= 21600`): the cap MAY retire (delete the rule from `score_caps.yaml`) OR reframe to `soak_evidence_not_recent` (e.g. cap=85, fires when no `provenance: real` soak in the last 30 d). RIA explicitly leaves which path is chosen to the platform team. Recommended: **reframe**, because the architectural-feasibility lens benefits from a freshness signal that does not vanish entirely.
2. **6h pass that surfaces a defect** (`duration_seconds >= 21600`, but one or more invariants did not hold OR the SIGTERM resume failed): cap **reframes** to a defect-tracking cap (e.g. `soak_surfaced_class_<id>`) at the same value pending the defect's own three-part closure. The defect goes to the W37 backlog; the soak itself is a successful deliverable per Lens 7.
3. **Run aborts before 6h** (CI runner timeout, infra failure, harness bug surfaced before the duration band is reached): cap **stays** at 75; the run is documented in the closure notice as a re-run candidate; the next scheduled overnight slot picks it up.

The decision in all three branches is reasoned **from the soak data**, recorded in the closure notice, and accompanied by a `score_caps.yaml` diff (or no diff, in branch 3). Manual score increases remain prohibited per Rule 14.

## 7. Three-Part Closure (Rule 15)

Per Rule 15, every defect-closure / supplement-closure carries three rows:

**(a) Code path**

- `.github/workflows/wave36-linux-soak.yml` (new)
- `scripts/run_soak.py` invocation as in §5 (no script edits required for §5; one `_evidence_filename` branch may be added if §2's to-confirm resolves to `-soak-6h.json`)
- `tests/chaos/scenarios/11_signal_storm_posix.py` (new)
- `tests/chaos/scenarios/12_fd_exhaustion_recovery_posix.py` (new)

**(b) Recurrence-prevention check**

- Extend `scripts/check_soak_evidence.py` (already the gate at `.github/workflows/release-gate.yml:146-151`) with a new branch: when the latest `*-soak-*.json` for HEAD is present but `provenance != "real"` OR `duration_seconds < 21600` OR `invariants_held: false`, fail with a structured reason. Today the script only validates `*-arch-7x24.json` (file:57-68); the soak-evidence path is missing despite the script name. The W36 extension closes that gap.
- Acceptance: `python scripts/check_soak_evidence.py --json --strict` exits 1 when any soak-evidence file at HEAD lacks `provenance:real` after the 6h band threshold has been exercised.

**(c) Process change**

- `CLAUDE.md` Rule 8 §architectural 7×24 currently lists 5 assertions and explicitly reframes the old 24h-soak as architectural. The W36 process change adds a 6th *non-blocking* note: the wall-clock 6h Linux soak is a measurement opportunity, separately tracked, with its own evidence file and its own cap rule. The 5 architectural assertions remain the binding shape.
- `docs/governance/retention-roadmap.md` (referenced for Tier-1 retention adoption in A3) gets a one-line cross-reference to this plan, recording that the 6h soak is the load source under which Tier-1 retention background tasks are exercised at scale.
- W36 delivery-notice template adds the §W36-S-1 closure block in §4.3 above.

## 8. Acceptance Criteria

- [ ] Plan published at `docs/superpowers/plans/2026-05-07-wave-36-linux-soak.md` (this file).
- [ ] CI workflow file `.github/workflows/wave36-linux-soak.yml` exists; `workflow_dispatch` trigger works.
- [ ] `tests/chaos/scenarios/11_signal_storm_posix.py` and `12_fd_exhaustion_recovery_posix.py` exist with POSIX `skipif` guards.
- [ ] 6h soak run completes with `provenance: real` at the W36 release HEAD and evidence is committed.
- [ ] arch-7×24 5/5 PASS re-run exists at the same HEAD with `chaos_runtime_coupled_all: PASS`.
- [ ] Cap disposition decision (retire / reframe / stay) reasoned from soak data and recorded in W36 closure notice §W36-S-1.
- [ ] Delivery-notice template for W36 carries §W36-S-1 with the three-part closure block.
- [ ] `check_soak_evidence.py` extension lands; `release-gate.yml` step §146 stays green at HEAD.

## 9. Sequencing (≤14 days)

- **Day 1-2:** workflow file + `check_soak_evidence.py` soak-evidence branch + skeletons for `11_signal_storm_posix.py` and `12_fd_exhaustion_recovery_posix.py`.
- **Day 3-7:** chaos-scenario authoring; offline pytest with the POSIX guards in place; `run_chaos_runtime_coupled.py` reports 12 scenarios, on Linux 0 skipped.
- **Day 8:** 1h shape-verified dry-run on `ubuntu-latest` via `workflow_dispatch` (`--duration 1h`); confirms harness emits `provenance: real (1h)` and the new scenarios participate.
- **Day 9-10:** 6h real run via the scheduled Friday-22:00-UTC slot; evidence committed at run HEAD via the operator pattern.
- **Day 11-12:** arch-7×24 re-run at the soak HEAD; manifest re-roll if needed (Rule 14 §functional-commit ordering — manifest follows soak commit, never precedes).
- **Day 13-14:** cap disposition decision; W36 delivery-notice §W36-S-1 lands; `score_caps.yaml` diff committed if disposition is retire/reframe.

## 10. Risk Registry

1. **GitHub-runner 6h ceiling.** `ubuntu-latest` jobs default to 360-min `timeout-minutes`; we set explicit `timeout-minutes: 420` for the 30 min buffer. A Free-tier billing limit may still cancel. **Mitigation per RIA amendment §2.2: if the GitHub `ubuntu-latest` budget ceiling is hit during the 6h band, halt the soak and request explicit RIA approval (48h SLA) before falling back to a 4h band. Do not ship `provenance: real (240m)` as W36-S-1 closure without this approval.** The CI workflow MUST NOT silently downgrade duration; the 4h fallback path is gated by an explicit operator decision (RIA-side), recorded in `docs/upstream-directives/` if exercised. Implementation: workflow defines only the 6h job; a 4h job exists as a separate `workflow_dispatch`-only entry that requires manual invocation with a recorded RIA-approval reference in the dispatch comment.
2. **Chaos-scenario non-determinism.** Signal storms and FD exhaustion produce non-deterministic timing. Mitigation: seed RNG in the new scenarios; assert on bounded ranges (e.g. "between 0 and 5 silent_degradation events"), not point values; keep `provenance: real` but with explicitly-documented bounded variance in the scenario docstring.
3. **SQLite WAL contention at N=50.** Tier-1 retention adoption (A3 plan, parallel) lands chunked DELETEs on the same SQLite files; under N=50 concurrency, write-lock pressure may produce the `database is locked` class. Mitigation: WAL mode is already on; document expected p99 envelope; if observed p99 widens beyond `concurrency-methodology-v1.md` baseline, that is a **successful Lens 7 finding** and reframes the cap per §6 branch 2.
4. **Soak-run interruption by orchestrator.** GitHub may evict the runner; the harness writes evidence at end-of-run, so a mid-run eviction loses all of it. Mitigation: `--resume` mode is W37 work; for W36 we accept the re-run cost and pick the next overnight slot. Branch 3 of §6 covers cap behaviour.
5. **`--mid-soak-sigterm-after 180` interaction with chaos cadence.** A SIGTERM at 3h could land during a `signal_storm` injection; the harness already pauses worker polling on `server_restart_event` (`scripts/run_soak.py:1058,1098-1100`). Mitigation: the 30s chaos cadence offsets are random-enough that collision is rare; a second SIGTERM later in the run is a future enhancement, not W36 scope.
6. **Filename-band drift.** RESOLVED per RIA amendment §2.3: `_evidence_filename` adds a 6h branch returning `-soak-6h.json` for `requested_duration_seconds == 21600`; the existing 240m branch is reserved for the 4h fallback only. The single-line change lands as part of the W36-S-1 implementation.

## 11. References

- RIA W36 supplement directive: `D:\chao_workspace\research\docs\hi-agent-w35-corrective-acceptance-and-w36-supplement-directive-2026-05-07.md` §2.1
- W34 Linux-soak roadmap: `docs/downstream-responses/2026-05-05-w34-delivery-notice.md:140-146`
- W36 entry directive (predecessor): `docs/upstream-directives/2026-05-05-hi-agent-wave36-engineering-expectations.md` §5
- Soak harness: `scripts/run_soak.py:1-1337` (full file; key lines noted inline)
- Arch-7×24 driver: `scripts/run_arch_7x24.py:1-80`
- Soak/arch evidence gate: `scripts/check_soak_evidence.py:1-175`
- Chaos runtime-coupled driver: `scripts/run_chaos_runtime_coupled.py:1-100`, `:507-530`
- Cap rule: `docs/governance/score_caps.yaml:173-178`
- Provenance schema: `docs/governance/evidence-provenance-schema.md`
- Retention roadmap (cross-reference for Tier-1 load source): `docs/governance/retention-roadmap.md`
- Sibling W36 plans: `docs/superpowers/plans/2026-05-06-wave-36-a3-tier1-retention-adoption.md`, `…-a4-schema-lineage-extensions.md`, `…-a5-boot-time-assertions.md`
- CLAUDE.md Rule 8 §architectural 7×24 (5 assertions reframe of the old 24h soak)

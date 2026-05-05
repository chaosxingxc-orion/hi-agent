# Concurrency Benchmark Methodology v1 (W34)

**Wave:** 34
**Closes:** W34-CONCURRENCY-METHOD (RIA §6 / B-W34-7)
**Status:** v1 — first formal methodology; subsequent waves may revise per RIA §10.1.

---

## 1. Purpose

Provide a reproducible, CI-runnable concurrency baseline so RIA can size
per-tenant rate limits and burst-handling shapes (`ria/user/budget.py`,
`ria/api/http/`) against measured platform numbers rather than estimated
ones. The methodology is intentionally minimal at v1 — a stable, repeatable
shape is more valuable than a deeply parameterised one we cannot reproduce.

---

## 2. Workload

The workload is **`N` parallel `POST /v1/runs` from `M` simulated tenants**:

- Each request body declares a unique `tenant_id` (`tenant-{i % M}`),
  `idempotency_key` (`run-bench-{i}`), `profile_id="default"`, `goal`
  (a static smoke-shape goal that does not require an LLM).
- Tenant assignment is round-robin (`i % M`), so tenants are
  evenly-loaded.
- Goal: every request reaches state `queued` (the durable enqueue) within
  the timeout. Stage progression (`S1`–`S5`) is OUT of scope at v1; the
  benchmark measures the API + queue + persistence path, not the LLM
  pipeline.

**N values:** `{1, 10, 50}` at v1 baseline. RIA's wishlist `N=100` is
deferred until CI runner stability is confirmed at `N=50`.

**M values:** `{1, 5}` at v1.

---

## 3. Measurement

Per-request:
- **start_run latency** — the wall-clock from `POST /v1/runs` send to
  receipt of `201 Created` containing `run_id`.

Per-run-collection:
- **P50, P95, P99** of start-run latency.
- **per-tenant fairness coefficient** — ratio of slowest-tenant median
  latency to fastest-tenant median latency. `1.0` is perfectly fair;
  larger values indicate per-tenant starvation.
- **queue depth time series** — sampled every 100 ms during the run via
  `/v1/manifest` or an ops-routes endpoint; measures backpressure shape.
- **SQLite lock-wait count** — drawn from sqlite's `database_locked`
  pragma counter. Indicates write contention under load.

---

## 4. Hardware Target

The canonical reference hardware is the **GitHub Actions
`ubuntu-latest` runner** (4 vCPU, 16 GB RAM, SSD, Linux). Baseline
artifacts emitted from this runner are the headline numbers.

Operators reproducing the benchmark on different hardware should scale
their expectations linearly with vCPU count (the workload is CPU-bound on
the JSON-encode/decode + SQLite-write path) and inversely with disk write
latency.

---

## 5. Procedure

```
# 1. Build the production app under default-offline backend (stub kernel)
#    so the run reaches `queued` deterministically; OR under real backend
#    if measuring kernel persistence.
export AGENT_SERVER_BACKEND=stub          # for API+queue baseline
export HI_AGENT_POSTURE=dev
export HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true

# 2. Boot the server on a free port via the CLI:
python -m agent_server.cli.main serve \
    --host 127.0.0.1 \
    --port 18080 \
    --state-dir /tmp/concurrency-bench

# 3. In a separate process, run the harness:
python scripts/run_concurrency_baseline.py \
    --server http://127.0.0.1:18080 \
    --concurrency 50 \
    --tenants 5 \
    --output docs/verification/<sha>-concurrency-N50M5.json

# 4. The harness writes a JSON artifact carrying `provenance: real`
#    (real = the server is a real subprocess, not a TestClient mock).
```

---

## 6. Output Artifact Shape

```json
{
  "schema": "hi-agent.concurrency-baseline.v1",
  "head_sha": "<git rev-parse --short HEAD>",
  "provenance": "real",
  "params": {"N": 50, "M": 5, "backend": "stub"},
  "wall_clock_seconds": <float>,
  "results": {
    "p50_ms": <float>,
    "p95_ms": <float>,
    "p99_ms": <float>,
    "max_ms": <float>,
    "throughput_rps": <float>,
    "successes": <int>,
    "failures": <int>,
    "fairness_coefficient": <float>
  },
  "per_tenant": {
    "tenant-0": {"requests": <int>, "p50_ms": <float>, "p95_ms": <float>},
    ...
  },
  "platform": {
    "python": "<sys.version>",
    "platform": "<sys.platform>",
    "cpu_count": <int>
  }
}
```

The artifact path is `docs/verification/<head>-concurrency-N{N}M{M}.json`
where `<head>` is the short git SHA at which the benchmark was run.
`scripts/check_concurrency_evidence.py` (W34) verifies the latest
artifact at HEAD has `provenance: real` and at least the headline P95.

---

## 7. Equivalence (SQLite vs PostgreSQL)

A separate equivalence test
(`tests/integration/test_concurrency_persistence_swap.py`) runs the same
workload at `N=10, M=1` against both persistence backends and asserts the
terminal-state distribution matches. The test does NOT compare latency
distributions — equivalence is about correctness, not performance.

---

## 8. Limitations and Future Work

- **v1 measures the API+queue+persistence path only.** LLM-bound
  end-to-end runs are tracked separately under Rule 8 T3.
- **Single-process measurement.** Multi-worker / multi-replica concurrency
  is out of scope at v1; cross-process fairness is meaningful only after
  durable cross-process idempotency is exercised (deferred).
- **`N=100` deferred.** Once `N=50` produces stable artifacts across 5
  consecutive CI runs, the methodology will raise N. Documented in W35
  carryover if not closed in W34.
- **Per-tenant fairness coefficient is a single scalar.** Future versions
  may emit a histogram of per-tenant latency to surface tail-latency
  starvation under burstier workloads.

---

## 9. Regression Budget (proposed for W35)

Once a stable baseline is recorded, future waves should adopt:

> P95 start-run latency at `N=50, M=5` must not exceed the previous
> wave's P95 by more than 25% without an explicit acceptance entry in
> the wave's delivery notice.

This is a proposal — RIA's §10.1 explicitly says they want a baseline
first; the budget shape will be settled in W35 once we have at least one
prior measurement to compare against.

---

**End of methodology v1.**

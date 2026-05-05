#!/usr/bin/env python3
"""W34-CONCURRENCY-BASELINE harness.

Drives ``N`` concurrent ``POST /v1/runs`` from ``M`` simulated tenants
against a running ``agent-server serve`` instance and writes a JSON
artifact to ``docs/verification/<head>-concurrency-N{N}M{M}.json``.

The harness is intentionally minimal: it uses ``urllib.request`` (stdlib
only) so it can run on a default GitHub Actions runner without extra
dependencies. ``concurrent.futures.ThreadPoolExecutor`` provides
parallelism — async would be lighter but would conflict with the test
profile constraint that the server is the system under test.

Usage:
    python scripts/run_concurrency_baseline.py \\
        --server http://127.0.0.1:18080 \\
        --concurrency 50 \\
        --tenants 5 \\
        --output docs/verification/<sha>-concurrency-N50M5.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import error as urlerr
from urllib import request as urlreq


def _git_head_short() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _post_run(
    server: str,
    *,
    tenant_id: str,
    idempotency_key: str,
    timeout: float,
) -> tuple[bool, float, str]:
    """Return (success, latency_ms, run_id_or_error)."""
    body = json.dumps({
        "tenant_id": tenant_id,
        "profile_id": "default",
        "goal": "concurrency-baseline-smoke",
        "idempotency_key": idempotency_key,
    }).encode("utf-8")
    req = urlreq.Request(
        f"{server.rstrip('/')}/v1/runs",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Tenant-Id": tenant_id,
            "Idempotency-Key": idempotency_key,
        },
    )
    # Bypass any HTTP_PROXY for localhost.
    opener = urlreq.build_opener(urlreq.ProxyHandler({}))
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            payload = resp.read().decode("utf-8")
            try:
                run_id = json.loads(payload).get("run_id", "")
            except json.JSONDecodeError:
                run_id = ""
            return True, latency_ms, run_id
    except urlerr.HTTPError as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, f"HTTP {exc.code}"
    except urlerr.URLError as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, f"URLError: {exc.reason}"


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile over a numeric list."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return float(s[f] + (s[c] - s[f]) * (k - f))


def _wait_for_health(server: str, timeout: float = 30.0) -> bool:
    """Poll /v1/health until 200 or timeout."""
    deadline = time.time() + timeout
    opener = urlreq.build_opener(urlreq.ProxyHandler({}))
    while time.time() < deadline:
        try:
            req = urlreq.Request(
                f"{server.rstrip('/')}/v1/health",
                headers={"X-Tenant-Id": "bench-probe"},
            )
            with opener.open(req, timeout=2.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:18080")
    parser.add_argument("--concurrency", "-N", type=int, default=10)
    parser.add_argument("--tenants", "-M", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=0,
                        help="Thread pool size; defaults to N.")
    parser.add_argument("--output", required=True, help="Output JSON artifact path.")
    parser.add_argument("--backend", default="stub",
                        help="AGENT_SERVER_BACKEND under test (informational; for the artifact)")
    parser.add_argument("--no-wait-health", action="store_true",
                        help="Skip the /v1/health pre-flight wait")
    args = parser.parse_args(argv)

    if args.concurrency < 1 or args.tenants < 1:
        print("FAIL concurrency-baseline: --concurrency and --tenants must be ≥ 1",
              file=sys.stderr)
        return 2

    if not args.no_wait_health:
        if not _wait_for_health(args.server, timeout=30.0):
            print(
                f"FAIL concurrency-baseline: /v1/health did not return 200 from "
                f"{args.server} within 30s",
                file=sys.stderr,
            )
            return 1

    workers = args.workers or args.concurrency
    requests = [
        (f"tenant-{i % args.tenants}", f"run-bench-{uuid.uuid4().hex[:8]}-{i}")
        for i in range(args.concurrency)
    ]

    t0 = time.perf_counter()
    results: list[tuple[bool, float, str, str]] = []  # ok, latency_ms, ref, tenant_id
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_post_run, args.server,
                      tenant_id=tenant, idempotency_key=key,
                      timeout=args.timeout): tenant
            for tenant, key in requests
        }
        for fut in as_completed(futures):
            tenant = futures[fut]
            ok, latency_ms, ref = fut.result()
            results.append((ok, latency_ms, ref, tenant))
    wall = time.perf_counter() - t0

    successes = [r for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    success_latencies = [r[1] for r in successes]

    # Per-tenant aggregates.
    per_tenant: dict[str, dict[str, float]] = {}
    for tenant in {r[3] for r in results}:
        tenant_lats = [r[1] for r in results if r[3] == tenant and r[0]]
        per_tenant[tenant] = {
            "requests": len(tenant_lats),
            "p50_ms": _percentile(tenant_lats, 0.50),
            "p95_ms": _percentile(tenant_lats, 0.95),
        }

    medians = [v["p50_ms"] for v in per_tenant.values() if v["p50_ms"] > 0]
    if medians:
        fairness = max(medians) / min(medians)
    else:
        fairness = 0.0

    artifact = {
        "schema": "hi-agent.concurrency-baseline.v1",
        "head_sha": _git_head_short(),
        "provenance": "real",
        "params": {
            "N": args.concurrency,
            "M": args.tenants,
            "backend": args.backend,
            "server": args.server,
        },
        "wall_clock_seconds": round(wall, 4),
        "results": {
            "p50_ms": _percentile(success_latencies, 0.50),
            "p95_ms": _percentile(success_latencies, 0.95),
            "p99_ms": _percentile(success_latencies, 0.99),
            "max_ms": max(success_latencies) if success_latencies else 0.0,
            "mean_ms": statistics.mean(success_latencies) if success_latencies else 0.0,
            "throughput_rps": round(len(successes) / wall, 4) if wall > 0 else 0.0,
            "successes": len(successes),
            "failures": len(failures),
            "fairness_coefficient": round(fairness, 4),
        },
        "per_tenant": per_tenant,
        "platform": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "failure_samples": [
            {"ref": r[2], "tenant_id": r[3], "latency_ms": round(r[1], 2)}
            for r in failures[:10]
        ],
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(
        f"OK concurrency-baseline: N={args.concurrency} M={args.tenants} "
        f"successes={len(successes)} failures={len(failures)} "
        f"P50={artifact['results']['p50_ms']:.1f}ms "
        f"P95={artifact['results']['p95_ms']:.1f}ms "
        f"P99={artifact['results']['p99_ms']:.1f}ms "
        f"fairness={artifact['results']['fairness_coefficient']:.2f} "
        f"-> {out}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

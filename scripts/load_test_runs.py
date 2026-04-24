"""Simple concurrent load test for hi-agent /runs endpoint.

Usage:
  python scripts/load_test_runs.py --base-url http://127.0.0.1:8080 \
      --requests 1000 --concurrency 100
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestResult:
    """Single request outcome for load-test aggregation."""

    status_code: int
    latency_ms: float
    error: str = ""


@dataclass(frozen=True)
class MetricsSample:
    """One sampled metrics snapshot during load test."""

    t_s: float
    queue_utilization: float
    runs_active: float
    runs_queued: float
    queue_full_rejections_total: float
    queue_timeouts_total: float


def _post_run(base_url: str, timeout_s: float) -> RequestResult:
    """Submit one run request and measure latency."""
    payload = {
        "task_id": f"load-{uuid.uuid4().hex[:12]}",
        "goal": "load-test synthetic task",
        "task_family": "quick_task",
        "risk_level": "low",
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/runs",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            _ = response.read()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return RequestResult(status_code=int(response.status), latency_ms=elapsed_ms)
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return RequestResult(status_code=int(exc.code), latency_ms=elapsed_ms, error="http_error")
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return RequestResult(status_code=0, latency_ms=elapsed_ms, error=str(exc))


def _extract_metric_total(payload: dict, key: str) -> float:
    item = payload.get(key)
    if not isinstance(item, dict):
        return 0.0
    if "_total" in item:
        return float(item["_total"])
    if not item:
        return 0.0
    # Fallback: pick first label bucket.
    first_key = next(iter(item))
    return float(item[first_key])


def _get_metrics_sample(base_url: str, timeout_s: float, t_s: float) -> MetricsSample | None:
    """Fetch /metrics/json and convert to compact queue-related sample."""
    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/metrics/json",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read()
        payload = json.loads(body.decode("utf-8"))
        return MetricsSample(
            t_s=t_s,
            queue_utilization=_extract_metric_total(payload, "server_queue_utilization"),
            runs_active=_extract_metric_total(payload, "server_runs_active"),
            runs_queued=_extract_metric_total(payload, "server_runs_queued"),
            queue_full_rejections_total=_extract_metric_total(
                payload, "server_queue_full_rejections_total"
            ),
            queue_timeouts_total=_extract_metric_total(payload, "server_queue_timeouts_total"),
        )
    except Exception:
        return None


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(ratio * len(ordered)) - 1))
    return ordered[idx]


def _print_metrics_trend(samples: list[MetricsSample]) -> None:
    """Print sampled queue-pressure trend summary."""
    if not samples:
        print("metrics_samples: 0")
        return
    q_util = [s.queue_utilization for s in samples]
    print(f"metrics_samples: {len(samples)}")
    print(f"queue_util_max: {max(q_util):.3f}")
    print(f"queue_util_p95: {_percentile(q_util, 0.95):.3f}")
    print(f"runs_active_max: {max(s.runs_active for s in samples):.0f}")
    print(f"runs_queued_max: {max(s.runs_queued for s in samples):.0f}")
    first = samples[0]
    last = samples[-1]
    print(
        "queue_full_rejections_delta: "
        f"{max(0.0, last.queue_full_rejections_total - first.queue_full_rejections_total):.0f}"
    )
    print(
        "queue_timeouts_delta: "
        f"{max(0.0, last.queue_timeouts_total - first.queue_timeouts_total):.0f}"
    )


def run_load_test(
    base_url: str,
    total_requests: int,
    concurrency: int,
    timeout_s: float,
    duration_s: float,
    sample_interval_s: float,
) -> int:
    """Execute load test and print summary report."""
    started = time.perf_counter()
    results: list[RequestResult] = []
    samples: list[MetricsSample] = []

    stop_sampling = threading.Event()

    def _sampler() -> None:
        while not stop_sampling.is_set():
            t_s = time.perf_counter() - started
            sample = _get_metrics_sample(base_url, timeout_s, t_s)
            if sample is not None:
                samples.append(sample)
            stop_sampling.wait(sample_interval_s)

    sampler_thread = threading.Thread(target=_sampler, daemon=True)
    sampler_thread.start()

    deadline = started + duration_s if duration_s > 0 else None
    submitted = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while True:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            if deadline is None and submitted >= total_requests:
                break

            if deadline is None:
                batch_size = min(concurrency, total_requests - submitted)
            else:
                batch_size = concurrency
            if batch_size <= 0:
                break

            futures = [pool.submit(_post_run, base_url, timeout_s) for _ in range(batch_size)]
            submitted += batch_size
            for future in as_completed(futures):
                results.append(future.result())

    stop_sampling.set()
    sampler_thread.join(timeout=max(1.0, sample_interval_s * 2))
    final_sample = _get_metrics_sample(base_url, timeout_s, time.perf_counter() - started)
    if final_sample is not None:
        samples.append(final_sample)

    duration_s = time.perf_counter() - started
    latencies = [r.latency_ms for r in results]
    success = sum(1 for r in results if r.status_code == 201)
    queue_full = sum(1 for r in results if r.status_code == 503)
    failed = len(results) - success
    rps = len(results) / duration_s if duration_s > 0 else 0.0

    print("=== hi-agent /runs Load Test ===")
    print(f"base_url: {base_url}")
    print(f"requests: {total_requests}")
    print(f"concurrency: {concurrency}")
    print(f"duration_s: {duration_s:.3f}")
    print(f"throughput_rps: {rps:.2f}")
    print(f"success_201: {success}")
    print(f"failed_total: {failed}")
    print(f"http_503: {queue_full}")
    print(f"latency_p50_ms: {_percentile(latencies, 0.50):.2f}")
    print(f"latency_p95_ms: {_percentile(latencies, 0.95):.2f}")
    print(f"latency_p99_ms: {_percentile(latencies, 0.99):.2f}")
    print(f"latency_avg_ms: {statistics.fmean(latencies) if latencies else 0.0:.2f}")
    _print_metrics_trend(samples)

    return 0 if success > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test hi-agent /runs endpoint.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0.0,
        help="If >0, run load test for this duration instead of fixed request count.",
    )
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout seconds.")
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=2.0,
        help="Seconds between /metrics/json samples.",
    )
    args = parser.parse_args()
    return run_load_test(
        base_url=args.base_url,
        total_requests=max(1, args.requests),
        concurrency=max(1, args.concurrency),
        timeout_s=max(0.1, args.timeout),
        duration_s=max(0.0, args.duration_seconds),
        sample_interval_s=max(0.2, args.sample_interval),
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Soak driver script for hi-agent — time-budget loop with sampler thread.

Runs for --duration-seconds wall time, submitting sequential runs and sampling
system health every --sample-interval-seconds. Emits a JSON evidence file.

Usage:
    # 1h smoke run against a live server (requires real LLM):
    python scripts/soak_24h.py --duration-seconds 3600 --provider volces

    # Dry run (no HTTP calls, generates structure evidence):
    python scripts/soak_24h.py --duration-seconds 60 --dry-run

    # Against a local server with default-offline mock:
    python scripts/soak_24h.py --duration-seconds 300 --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _git_sha_full() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _process_rss_mb() -> float:
    """Return resident set size in MB for the current process."""
    try:
        import psutil
        p = psutil.Process(os.getpid())
        return round(p.memory_info().rss / 1024 / 1024, 2)
    except Exception:
        return 0.0


def _cpu_percent() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=None)
    except Exception:
        return 0.0


def _dlq_depth(base_url: str) -> int:
    """Query /ops/dlq for dead-lettered run count."""
    try:
        import httpx
        r = httpx.get(f"{base_url}/ops/dlq", timeout=3.0, trust_env=False)
        if r.status_code == 200:
            data = r.json()
            return len(data.get("runs", data if isinstance(data, list) else []))
    except Exception:
        pass
    return 0


def _queue_depth(base_url: str) -> int:
    """Estimate queue depth from /ready endpoint."""
    try:
        import httpx
        r = httpx.get(f"{base_url}/ready", timeout=3.0, trust_env=False)
        if r.status_code == 200:
            data = r.json()
            return int(data.get("queue_depth", 0))
    except Exception:
        pass
    return 0


class _SamplerThread:
    """Background thread that samples system health every interval_seconds."""

    def __init__(self, base_url: str, interval_seconds: float = 30.0) -> None:
        self._base_url = base_url
        self._interval = interval_seconds
        self._samples: list[dict] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="soak-sampler"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=self._interval + 5.0)

    def samples(self) -> list[dict]:
        with self._lock:
            return list(self._samples)

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            sample = {
                "ts": _iso_now(),
                "rss_mb": _process_rss_mb(),
                "cpu_pct": _cpu_percent(),
                "dlq_depth": _dlq_depth(self._base_url),
                "queue_depth": _queue_depth(self._base_url),
            }
            with self._lock:
                self._samples.append(sample)


def _server_reachable(base_url: str) -> bool:
    try:
        import httpx
        r = httpx.get(f"{base_url}/ready", timeout=5.0, trust_env=False)
        return r.status_code in (200, 503)
    except Exception:
        return False


def _submit_run(base_url: str, provider: str, run_index: int) -> dict:
    """Submit one run and wait for terminal state. Returns result dict."""
    import httpx

    payload = {
        "goal": f"soak-run-{run_index}",
        "profile_id": "soak_test",
        "project_id": "soak_test_project",
    }
    t0 = time.monotonic()
    run_id = None
    state = "unknown"
    error = None
    try:
        c = httpx.Client(timeout=httpx.Timeout(10.0), trust_env=False)
        resp = c.post(f"{base_url}/runs", json=payload)
        if resp.status_code not in (200, 201, 202):
            error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return {
                "run_index": run_index,
                "run_id": None,
                "state": "http_error",
                "duration_seconds": round(time.monotonic() - t0, 3),
                "error": error,
            }
        body = resp.json()
        run_id = body.get("run_id") or body.get("id")
        deadline = time.monotonic() + 600.0  # 10 min; Volces model may take ~6 min/run
        while time.monotonic() < deadline:
            poll = c.get(f"{base_url}/runs/{run_id}")
            if poll.status_code == 200:
                info = poll.json()
                state = info.get("state", "unknown")
                if state in ("completed", "failed", "cancelled", "done", "error"):
                    break
            time.sleep(2.0)
        else:
            state = "timeout"
        c.close()
    except Exception as exc:
        error = str(exc)
        state = "exception"

    return {
        "run_index": run_index,
        "run_id": run_id,
        "state": state,
        "duration_seconds": round(time.monotonic() - t0, 3),
        "error": error,
    }


def _dummy_run(run_index: int, elapsed_s: float) -> dict:
    return {
        "run_index": run_index,
        "run_id": f"dry-run-{run_index:04d}",
        "state": "dry_run",
        "duration_seconds": 0.0,
        "elapsed_wall_seconds": round(elapsed_s, 1),
        "error": None,
    }


def _write_evidence(
    sha: str,
    full_sha: str,
    start_time: str,
    end_time: str,
    duration_seconds: float,
    results: list[dict],
    samples: list[dict],
    dry_run: bool,
    sigterm_injections: int,
    out_dir: Path,
) -> Path:
    runs_submitted = len(results)
    runs_completed = sum(
        1 for r in results if r["state"] in ("completed", "done", "dry_run")
    )
    runs_failed = sum(
        1 for r in results if r["state"] not in ("completed", "done", "dry_run")
    )

    label = "soak-dry" if dry_run else "soak"
    duration_min = round(duration_seconds / 60)
    filename = f"{sha}-{label}-{duration_min}m.json"
    out_path = out_dir / filename

    # Derive recovery counters from actual result states (not hardcoded).
    runs_with_errors = sum(1 for r in results if r.get("state") == "exception")
    # Duplicate detection: runs that share the same run_id (if server assigned duplicates).
    all_ids = [r.get("run_id") for r in results if r.get("run_id")]
    duplicate_executions = len(all_ids) - len(set(all_ids))

    _min_real_seconds = 86400.0  # 24h threshold for provenance:real
    if dry_run:
        provenance = "dry_run"
    elif duration_seconds >= _min_real_seconds:
        provenance = "real"
    else:
        provenance = "shape_verified"

    evidence = {
        "release_head": sha,
        "verified_head": full_sha,
        "check": "soak_evidence",
        "provenance": provenance,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(duration_seconds, 3),
        "status": "dry_run" if dry_run else "completed",
        "runs_submitted": runs_submitted,
        "runs_completed": runs_completed,
        "runs_failed": runs_failed,
        "runs_with_exceptions": runs_with_errors,
        "duplicate_executions": duplicate_executions,
        "sigterm_injections": sigterm_injections,
        "health_samples": samples,
        "alert_events": [],
        "operator_actions": [],
        "results": results,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return out_path


def _inject_sigterm(base_url: str) -> bool:
    """Ask the server to simulate graceful drain (if /ops/drain endpoint exists)."""
    try:
        import httpx
        r = httpx.post(f"{base_url}/ops/drain", timeout=5.0)
        return r.status_code in (200, 202, 204)
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hi-agent soak driver (time-budget)")
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=3600.0,
        help="Wall-time budget in seconds (default 3600 = 1h)",
    )
    parser.add_argument("--provider", default="volces", help="LLM provider name")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server base URL")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip HTTP calls; emit structure evidence only",
    )
    parser.add_argument(
        "--sample-interval-seconds", type=float, default=30.0,
        help="System health sample interval (default 30s)",
    )
    parser.add_argument(
        "--sigterm-interval-seconds", type=float, default=1800.0,
        help="Inject drain signal every N seconds (default 1800 = 30min; 0 to disable)",
    )
    parser.add_argument(
        "--run-interval-seconds", type=float, default=5.0,
        help="Seconds between run submissions (default 5)",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Output directory for evidence JSON (default: docs/verification/)",
    )
    args = parser.parse_args(argv)

    sha = _git_sha()
    full_sha = _git_sha_full()
    start_time = _iso_now()
    t_start = time.monotonic()
    deadline = t_start + args.duration_seconds

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = Path(__file__).parent.parent / "docs" / "verification"

    results: list[dict] = []
    sigterm_injections = 0

    # Start sampler thread.
    sampler = _SamplerThread(
        base_url=args.base_url,
        interval_seconds=args.sample_interval_seconds,
    )
    sampler.start()

    next_sigterm_t = t_start + args.sigterm_interval_seconds
    run_index = 0

    if args.dry_run:
        print(
            f"[soak] dry-run mode: running for {args.duration_seconds:.0f}s budget "
            f"(generating structure evidence, no HTTP calls)"
        )
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - t_start
            results.append(_dummy_run(run_index, elapsed))
            run_index += 1
            print(
                f"[soak] dry run {run_index}: elapsed={elapsed:.1f}s "
                f"/{args.duration_seconds:.0f}s"
            )
            sleep_until = min(
                time.monotonic() + args.run_interval_seconds, deadline
            )
            time.sleep(max(0.0, sleep_until - time.monotonic()))
    else:
        reachable = _server_reachable(args.base_url)
        if not reachable:
            print(
                f"[soak] WARNING: server not reachable at {args.base_url}; "
                "switching to dry-run mode"
            )
            sampler.stop()
            out_path = _write_evidence(
                sha=sha, full_sha=full_sha,
                start_time=start_time, end_time=_iso_now(),
                duration_seconds=0.0, results=[], samples=[],
                dry_run=True, sigterm_injections=0, out_dir=out_dir,
            )
            print(f"[soak] evidence written to {out_path}")
            return 1

        print(
            f"[soak] running for {args.duration_seconds:.0f}s "
            f"against {args.base_url} (provider={args.provider})"
        )
        while time.monotonic() < deadline:
            now = time.monotonic()
            # Periodic SIGTERM injection.
            if (
                args.sigterm_interval_seconds > 0
                and now >= next_sigterm_t
            ):
                injected = _inject_sigterm(args.base_url)
                if injected:
                    sigterm_injections += 1
                    print(
                        f"[soak] SIGTERM injected "
                        f"(total={sigterm_injections}) at t={now - t_start:.0f}s"
                    )
                next_sigterm_t = now + args.sigterm_interval_seconds

            result = _submit_run(args.base_url, args.provider, run_index)
            results.append(result)
            elapsed = time.monotonic() - t_start
            print(
                f"[soak] run {run_index + 1}: state={result['state']} "
                f"dur={result['duration_seconds']}s elapsed={elapsed:.0f}s"
            )
            run_index += 1
            # Sleep between runs (respect deadline).
            sleep_until = min(
                time.monotonic() + args.run_interval_seconds, deadline
            )
            time.sleep(max(0.0, sleep_until - time.monotonic()))

    sampler.stop()
    end_time = _iso_now()
    duration_seconds = time.monotonic() - t_start

    out_path = _write_evidence(
        sha=sha, full_sha=full_sha,
        start_time=start_time, end_time=end_time,
        duration_seconds=duration_seconds,
        results=results, samples=sampler.samples(),
        dry_run=args.dry_run, sigterm_injections=sigterm_injections,
        out_dir=out_dir,
    )

    runs_ok = sum(1 for r in results if r["state"] in ("completed", "done", "dry_run"))
    print(
        f"[soak] done: {runs_ok}/{len(results)} runs ok, "
        f"{sigterm_injections} SIGTERM injections, "
        f"duration={duration_seconds:.0f}s"
    )
    print(f"[soak] evidence written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

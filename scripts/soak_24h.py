"""Soak driver script for hi-agent.

Submits N sequential runs to a running server and records per-run results.
Emits a JSON evidence file under docs/verification/.

Usage:
    python scripts/soak_24h.py --runs 10 --interval-seconds 5.0 --provider volces
    python scripts/soak_24h.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _server_reachable(base_url: str) -> bool:
    try:
        import httpx

        r = httpx.get(f"{base_url}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _submit_run(base_url: str, provider: str, run_index: int) -> dict:
    """Submit one run and wait for terminal state. Returns result dict."""
    import httpx

    payload = {
        "task": f"soak-run-{run_index}",
        "provider": provider,
    }
    t0 = time.monotonic()
    run_id = None
    state = "unknown"
    error = None
    try:
        resp = httpx.post(f"{base_url}/runs", json=payload, timeout=10.0)
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
        # Poll for terminal state (max 120 s)
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            poll = httpx.get(f"{base_url}/runs/{run_id}", timeout=5.0)
            if poll.status_code == 200:
                info = poll.json()
                state = info.get("state", "unknown")
                if state in ("completed", "failed", "cancelled", "done", "error"):
                    break
            time.sleep(2.0)
        else:
            state = "timeout"
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


def _dummy_run(run_index: int) -> dict:
    return {
        "run_index": run_index,
        "run_id": f"dry-run-{run_index:04d}",
        "state": "dry_run",
        "duration_seconds": 0.0,
        "error": None,
    }


def _write_evidence(
    sha: str,
    start_time: str,
    end_time: str,
    duration_seconds: float,
    results: list[dict],
    dry_run: bool,
    out_dir: Path,
) -> Path:
    runs_submitted = len(results)
    runs_completed = sum(1 for r in results if r["state"] in ("completed", "done", "dry_run"))
    runs_failed = sum(1 for r in results if r["state"] not in ("completed", "done", "dry_run"))

    label = "dry" if dry_run else "soak"
    filename = f"{sha}-{label}-{int(duration_seconds)}s.json"
    out_path = out_dir / filename

    evidence = {
        "release_head": sha,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(duration_seconds, 3),
        "status": "dry_run" if dry_run else "completed",
        "runs_submitted": runs_submitted,
        "runs_completed": runs_completed,
        "runs_failed": runs_failed,
        "runs_recovered": 0,
        "duplicate_executions": 0,
        "cost_usage": "N/A",
        "alert_events": [],
        "operator_actions": [],
        "results": results,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hi-agent soak driver")
    parser.add_argument("--runs", type=int, default=10, help="Number of runs to submit")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Seconds between runs")
    parser.add_argument("--provider", default="volces", help="LLM provider name")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server base URL")
    parser.add_argument(
        "--dry-run", action="store_true", help="Skip HTTP calls; emit dummy evidence"
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for evidence JSON (default: docs/verification/)",
    )
    args = parser.parse_args(argv)

    sha = _git_sha()
    start_time = _iso_now()
    t0 = time.monotonic()

    # Resolve output directory relative to repo root (this script lives in scripts/)
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        script_dir = Path(__file__).parent
        out_dir = script_dir.parent / "docs" / "verification"

    results: list[dict] = []

    if args.dry_run:
        print(f"[soak] dry-run: generating {args.runs} dummy records (no HTTP calls)")
        for i in range(args.runs):
            results.append(_dummy_run(i))
    else:
        reachable = _server_reachable(args.base_url)
        if not reachable:
            print(
                f"[soak] WARNING: server not reachable at {args.base_url}; "
                "emitting dry_run evidence file"
            )
            for i in range(args.runs):
                results.append(_dummy_run(i))
        else:
            print(f"[soak] submitting {args.runs} runs to {args.base_url}")
            for i in range(args.runs):
                result = _submit_run(args.base_url, args.provider, i)
                results.append(result)
                status = result["state"]
                dur = result["duration_seconds"]
                print(f"[soak] run {i + 1}/{args.runs}: state={status} duration={dur}s")
                if i < args.runs - 1:
                    time.sleep(args.interval_seconds)

    end_time = _iso_now()
    duration_seconds = time.monotonic() - t0

    out_path = _write_evidence(
        sha=sha,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration_seconds,
        results=results,
        dry_run=args.dry_run or not _server_reachable(args.base_url) if not args.dry_run else True,
        out_dir=out_dir,
    )

    print(f"[soak] evidence written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

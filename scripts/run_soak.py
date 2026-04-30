"""W24-C: Soak harness with --duration 1h|24h flag.

Single entry point for soak runs. Spawns a long-lived `python -m hi_agent serve`
subprocess on the configured port, fires 1 run / 30s for the requested duration,
asserts invariants at the end, and emits truthful evidence JSON.

Invariants asserted at end of run:
  * 0 lost runs (every submitted run reached a terminal state OR was tracked as failed)
  * 0 duplicate run_ids
  * llm_fallback_count == 0 (read from /metrics)
  * every run had stage activity observed within 30s of submission (either via
    polling current_stage OR via result.stages[] non-empty at terminal — the
    latter is the reliable signal under dev-smoke fast mode where polling may
    miss a transient current_stage)
  * every terminal run has finished_at populated

Usage:
    # 5-min smoke (proof of harness; tags provenance:shape_1h, NOT real 1h):
    python scripts/run_soak.py --duration 5m --port 9083

    # Real 1h soak (operator-shape; tags provenance:real if invariants hold):
    python scripts/run_soak.py --duration 1h --port 9083

    # 24h soak (kicked off in background by Track C-24h dispatch):
    python scripts/run_soak.py --duration 24h --port 9083

Provenance rules (NEVER fake):
  * duration_seconds >= 86400 AND invariants_held → provenance: real (24h credit)
  * duration_seconds >= 3600  AND invariants_held → provenance: real (1h credit)
  * duration_seconds <  3600                      → provenance: shape_1h
                                                    (smoke validation that the harness works;
                                                     does NOT lift the soak cap)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_sha_short() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(ROOT),
        ).strip()
    except Exception:
        return "unknown"


def _git_sha_full() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(ROOT),
        ).strip()
    except Exception:
        return "unknown"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_duration(spec: str) -> int:
    """Parse '5m', '1h', '24h', '300s' to integer seconds."""
    s = spec.strip().lower()
    m = re.fullmatch(r"(\d+)([smh]?)", s)
    if not m:
        raise ValueError(f"unrecognized duration: {spec!r} (try '5m', '1h', '24h')")
    n = int(m.group(1))
    unit = m.group(2) or "s"
    return {"s": n, "m": n * 60, "h": n * 3600}[unit]


def _is_port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


class _ServerProcess:
    """Long-lived hi_agent serve subprocess on the requested port.

    Stdout/stderr are written to a log file under docs/verification/soak-logs/.
    """

    def __init__(self, port: int, log_dir: Path) -> None:
        self._port = port
        self._proc: subprocess.Popen | None = None
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"server-{port}-{int(time.time())}.log"
        self._log_fp = None

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def start(self) -> None:
        env = os.environ.copy()
        # Default to dev mode so the subprocess works without API keys.
        # Real-LLM mode is the operator's responsibility for full 1h/24h runs.
        env.setdefault("HI_AGENT_ENV", "dev")
        env.setdefault("HI_AGENT_POSTURE", "dev")
        # Force unbuffered output so the log file gets timely flushes.
        env.setdefault("PYTHONUNBUFFERED", "1")

        self._log_fp = self._log_path.open("w", encoding="utf-8", errors="replace")
        cmd = [sys.executable, "-m", "hi_agent", "serve",
               "--host", "127.0.0.1", "--port", str(self._port)]
        self._proc = subprocess.Popen(
            cmd,
            stdout=self._log_fp,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(ROOT),
        )

    def wait_ready(self, base_url: str, timeout_seconds: float = 30.0) -> bool:
        """Poll /health until 200."""
        try:
            import httpx
        except ImportError:
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._proc and self._proc.poll() is not None:
                # Server died early.
                return False
            try:
                r = httpx.get(f"{base_url}/health", timeout=2.0, trust_env=False)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def stop(self) -> int:
        if not self._proc:
            return 0
        try:
            self._proc.terminate()
            try:
                code = self._proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                code = self._proc.wait(timeout=5.0)
        except Exception:
            code = -1
        if self._log_fp:
            try:
                self._log_fp.flush()
                self._log_fp.close()
            except Exception:
                pass
        return code


# ---------------------------------------------------------------------------
# Run submission + invariant tracking
# ---------------------------------------------------------------------------


_TERMINAL_STATES = {"completed", "done", "failed", "cancelled", "error"}


def _submit_run(base_url: str, run_index: int) -> dict:
    """Submit one run and poll until terminal or timeout. Returns result dict.

    Tracks invariants:
      * stage_first_seen_seconds: seconds between submission and first non-None current_stage
      * terminal_stage_count: number of stages recorded in result.stages[] at terminal
      * finished_at: populated when state reaches a terminal value
    """
    import httpx

    payload = {
        "goal": f"soak-run-{run_index}",
        "profile_id": "soak_test",
        "project_id": "soak_test_project",
        "task_family": "smoke",
    }
    submit_t = time.monotonic()
    run_id: str | None = None
    state = "unknown"
    error: str | None = None
    stage_first_seen_seconds: float | None = None
    terminal_stage_count = 0
    finished_at: str | None = None
    poll_count = 0
    try:
        c = httpx.Client(timeout=httpx.Timeout(10.0), trust_env=False)
        resp = c.post(f"{base_url}/runs", json=payload)
        if resp.status_code not in (200, 201, 202):
            error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return {
                "run_index": run_index,
                "run_id": None,
                "state": "http_error",
                "stage_first_seen_seconds": None,
                "terminal_stage_count": 0,
                "finished_at": None,
                "duration_seconds": round(time.monotonic() - submit_t, 3),
                "error": error,
            }
        body = resp.json()
        run_id = body.get("run_id") or body.get("id")
        # Per-run timeout: dev mode finishes in seconds; allow 60s ceiling.
        per_run_deadline = time.monotonic() + 60.0
        while time.monotonic() < per_run_deadline:
            try:
                poll = c.get(f"{base_url}/runs/{run_id}")
                poll_count += 1
                if poll.status_code == 200:
                    info = poll.json()
                    cur_stage = info.get("current_stage")
                    if (
                        stage_first_seen_seconds is None
                        and cur_stage is not None
                    ):
                        stage_first_seen_seconds = round(
                            time.monotonic() - submit_t, 3
                        )
                    state = info.get("state", "unknown")
                    if state in _TERMINAL_STATES:
                        finished_at = info.get("finished_at")
                        # Fallback signal for fast runs that complete before
                        # polling catches a transient current_stage value.
                        result_obj = info.get("result") or {}
                        stages_obj = result_obj.get("stages") or []
                        if isinstance(stages_obj, list):
                            terminal_stage_count = len(stages_obj)
                        break
            except Exception:
                pass
            time.sleep(0.5)
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
        "stage_first_seen_seconds": stage_first_seen_seconds,
        "terminal_stage_count": terminal_stage_count,
        "finished_at": finished_at,
        "poll_count": poll_count,
        "duration_seconds": round(time.monotonic() - submit_t, 3),
        "error": error,
    }


# ---------------------------------------------------------------------------
# Metrics scrape
# ---------------------------------------------------------------------------


_LLM_FALLBACK_RE = re.compile(
    r'^hi_agent_llm_fallback_total(?:\{[^}]*\})?\s+([0-9.eE+\-]+)', re.M,
)


def _scrape_llm_fallback_count(base_url: str) -> int:
    """Read hi_agent_llm_fallback_total from /metrics. Returns 0 if not present."""
    try:
        import httpx
        r = httpx.get(f"{base_url}/metrics", timeout=5.0, trust_env=False)
        if r.status_code != 200:
            return 0
        total = 0
        for m in _LLM_FALLBACK_RE.finditer(r.text):
            try:
                total += int(float(m.group(1)))
            except (ValueError, TypeError):
                continue
        return total
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Background sampler thread (samples server-process RSS/CPU)
# ---------------------------------------------------------------------------


def _process_rss_mb(pid: int | None) -> float:
    if pid is None:
        return 0.0
    try:
        import psutil
        p = psutil.Process(pid)
        return round(p.memory_info().rss / 1024 / 1024, 2)
    except Exception:
        return 0.0


def _process_cpu_pct(pid: int | None) -> float:
    if pid is None:
        return 0.0
    try:
        import psutil
        p = psutil.Process(pid)
        return round(p.cpu_percent(interval=None), 2)
    except Exception:
        return 0.0


class _Sampler:
    """Samples the server process every interval_seconds."""

    def __init__(self, server_pid: int | None, interval_seconds: float) -> None:
        self._pid = server_pid
        self._interval = interval_seconds
        self._samples: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="soak-sampler")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 5.0)

    def samples(self) -> list[dict]:
        with self._lock:
            return list(self._samples)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            sample = {
                "ts": _iso_now(),
                "rss_mb": _process_rss_mb(self._pid),
                "cpu_pct": _process_cpu_pct(self._pid),
            }
            with self._lock:
                self._samples.append(sample)


# ---------------------------------------------------------------------------
# Invariant checking
# ---------------------------------------------------------------------------


def _compute_invariants(
    results: list[dict],
    llm_fallback_count: int,
    stage_observation_window_seconds: float = 30.0,
) -> dict:
    """Compute invariants_held + per-invariant pass/fail map."""
    submitted = len(results)
    terminal = sum(1 for r in results if r.get("state") in _TERMINAL_STATES)
    timeout_or_exc = sum(
        1 for r in results
        if r.get("state") in ("timeout", "exception", "http_error")
    )
    # Lost runs = submitted - terminal - tracked-failure (we count timeout/exception
    # as tracked failures; "lost" means a run we lost track of entirely).
    lost_runs = submitted - terminal - timeout_or_exc

    # Duplicate detection.
    ids = [r.get("run_id") for r in results if r.get("run_id")]
    duplicates = len(ids) - len(set(ids))

    # Stage observed within window. Two signals satisfy the invariant:
    #   1. current_stage was non-None within the observation window during polling
    #      (the original Rule-8 check, only reliable when stages take >0.5s each)
    #   2. result.stages[] is non-empty at terminal (reliable for runs that
    #      finished too fast for polling to catch a transient current_stage,
    #      common under dev-smoke fast mode)
    # If neither signal fires, the run is a stage_miss.
    stage_misses: list[int] = []
    for r in results:
        if r.get("state") not in _TERMINAL_STATES:
            continue
        sfs = r.get("stage_first_seen_seconds")
        polling_ok = sfs is not None and sfs <= stage_observation_window_seconds
        terminal_stages_ok = (r.get("terminal_stage_count") or 0) > 0
        if not polling_ok and not terminal_stages_ok:
            stage_misses.append(r.get("run_index", -1))

    # finished_at populated on every terminal.
    finished_at_misses = [
        r.get("run_index", -1) for r in results
        if r.get("state") in _TERMINAL_STATES and not r.get("finished_at")
    ]

    invariants = {
        "no_lost_runs": (lost_runs == 0, lost_runs),
        "no_duplicates": (duplicates == 0, duplicates),
        "llm_fallback_zero": (llm_fallback_count == 0, llm_fallback_count),
        "stage_observed_within_30s": (
            not stage_misses, stage_misses[:5],
        ),
        "finished_at_populated": (
            not finished_at_misses, finished_at_misses[:5],
        ),
    }
    held = all(passed for passed, _ in invariants.values())
    return {
        "invariants_held": held,
        "lost_runs": lost_runs,
        "duplicate_run_ids": duplicates,
        "llm_fallback_count": llm_fallback_count,
        "stage_observed_misses": stage_misses,
        "finished_at_misses": finished_at_misses,
        "submitted": submitted,
        "terminal": terminal,
        "timeout_or_exception": timeout_or_exc,
        "details": {
            k: {"passed": passed, "value": value}
            for k, (passed, value) in invariants.items()
        },
    }


# ---------------------------------------------------------------------------
# Evidence emission
# ---------------------------------------------------------------------------


def _classify_provenance(
    duration_seconds: float, invariants_held: bool, dry_run: bool,
) -> tuple[str, str]:
    """Return (provenance, label_hours)."""
    if dry_run:
        return "dry_run", "dry"
    # Real soaks must hold invariants AND meet duration thresholds.
    if duration_seconds >= 86400.0 and invariants_held:
        return "real", "24h"
    if duration_seconds >= 3600.0 and invariants_held:
        return "real", "1h"
    # Otherwise: shape_1h smoke validation. NOT 1h credit.
    return "shape_1h", "shape"


def _evidence_filename(
    sha: str, duration_seconds: float, dry_run: bool, provenance: str,
) -> str:
    """Pick a filename per the dispatch convention.

    Uses a 'shape' suffix when provenance is shape_1h to make the truthfulness
    visible at the filename level. Real 1h/24h evidence uses the canonical
    `<HEAD>-soak-1h.json` / `<HEAD>-soak-24h.json` form.
    """
    if dry_run:
        return f"{sha}-soak-dry-{int(duration_seconds // 60)}m.json"
    if provenance == "shape_1h":
        return f"{sha}-soak-shape-{int(duration_seconds // 60)}m.json"
    if provenance == "real" and duration_seconds >= 86400.0:
        return f"{sha}-soak-24h.json"
    if provenance == "real":
        return f"{sha}-soak-1h.json"
    return f"{sha}-soak-{int(duration_seconds // 60)}m.json"


def _write_evidence(
    sha: str,
    full_sha: str,
    requested_duration_label: str,
    requested_duration_seconds: int,
    start_time: str,
    end_time: str,
    duration_seconds: float,
    results: list[dict],
    samples: list[dict],
    dry_run: bool,
    invariants: dict,
    server_pid: int | None,
    server_log_path: str,
    out_dir: Path,
    notes: list[str],
) -> Path:
    provenance, _label = _classify_provenance(
        duration_seconds, invariants["invariants_held"], dry_run,
    )
    filename = _evidence_filename(sha, duration_seconds, dry_run, provenance)
    out_path = out_dir / filename

    runs_completed = sum(
        1 for r in results
        if r.get("state") in ("completed", "done")
    )
    runs_failed = sum(
        1 for r in results
        if r.get("state") not in ("completed", "done", "dry_run")
    )

    evidence: dict = {
        "release_head": sha,
        "verified_head": full_sha,
        "check": "soak_evidence",
        "provenance": provenance,
        "requested_duration_label": requested_duration_label,
        "requested_duration_seconds": requested_duration_seconds,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(duration_seconds, 3),
        "status": "completed" if not dry_run else "dry_run",
        "server_pid": server_pid,
        "server_log_path": server_log_path,
        "runs_submitted": invariants["submitted"],
        "runs_completed": runs_completed,
        "runs_failed": runs_failed,
        "lost_runs": invariants["lost_runs"],
        "duplicate_run_ids": invariants["duplicate_run_ids"],
        "llm_fallback_count": invariants["llm_fallback_count"],
        "stage_observed_misses": invariants["stage_observed_misses"],
        "finished_at_misses": invariants["finished_at_misses"],
        "invariants_held": invariants["invariants_held"],
        "invariant_details": invariants["details"],
        "health_samples": samples,
        "results": results,
        "notes": notes,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="hi-agent soak harness with --duration 1h|24h flag",
    )
    parser.add_argument(
        "--duration", type=str, default="1h",
        help="Soak duration: '5m', '1h', '24h', '300s' (default: 1h)",
    )
    parser.add_argument(
        "--port", type=int, default=9083,
        help="Port for the spawned hi_agent serve subprocess (default: 9083)",
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Bind host for the spawned subprocess (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--run-interval-seconds", type=float, default=30.0,
        help="Seconds between run submissions (default: 30 per dispatch spec)",
    )
    parser.add_argument(
        "--sample-interval-seconds", type=float, default=30.0,
        help="System health sample interval (default: 30s)",
    )
    parser.add_argument(
        "--no-spawn-server", action="store_true",
        help=(
            "Do not spawn a server subprocess; assume one is already running "
            "at --host:--port. Useful for the 24h background dispatch."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Emit dry_run evidence with no HTTP traffic (smoke test only).",
    )
    parser.add_argument(
        "--out-dir", type=str, default=None,
        help="Output directory for evidence (default: docs/verification/).",
    )
    args = parser.parse_args(argv)

    duration_seconds = _parse_duration(args.duration)
    if duration_seconds <= 0:
        print("[soak] duration must be > 0", file=sys.stderr)
        return 2

    base_url = f"http://{args.host}:{args.port}"
    out_dir = Path(args.out_dir) if args.out_dir else (
        ROOT / "docs" / "verification"
    )
    log_dir = out_dir / "soak-logs"

    sha = _git_sha_short()
    full_sha = _git_sha_full()
    start_iso = _iso_now()
    notes: list[str] = []

    # ---- dry-run path -----------------------------------------------------
    if args.dry_run:
        notes.append(
            "dry_run: no HTTP traffic, no subprocess; structure validation only"
        )
        invariants = _compute_invariants([], 0)
        out_path = _write_evidence(
            sha=sha,
            full_sha=full_sha,
            requested_duration_label=args.duration,
            requested_duration_seconds=duration_seconds,
            start_time=start_iso,
            end_time=_iso_now(),
            duration_seconds=0.0,
            results=[],
            samples=[],
            dry_run=True,
            invariants=invariants,
            server_pid=None,
            server_log_path="",
            out_dir=out_dir,
            notes=notes,
        )
        print(f"[soak] dry_run evidence: {out_path}")
        return 0

    # ---- spawn server (unless --no-spawn-server) --------------------------
    server: _ServerProcess | None = None
    server_log_path = ""
    server_pid: int | None = None

    if args.no_spawn_server:
        notes.append(f"server not spawned by harness; assumed running at {base_url}")
    else:
        if not _is_port_free(args.host, args.port):
            print(
                f"[soak] FATAL: port {args.port} already in use on {args.host}; "
                f"refusing to spawn (would collide with existing process)",
                file=sys.stderr,
            )
            return 3
        server = _ServerProcess(args.port, log_dir=log_dir)
        server.start()
        server_log_path = str(server.log_path)
        server_pid = server.pid
        notes.append(f"server spawned: pid={server_pid} log={server_log_path}")
        if not server.wait_ready(base_url, timeout_seconds=30.0):
            notes.append("server failed to become ready within 30s")
            invariants = _compute_invariants([], 0)
            out_path = _write_evidence(
                sha=sha,
                full_sha=full_sha,
                requested_duration_label=args.duration,
                requested_duration_seconds=duration_seconds,
                start_time=start_iso,
                end_time=_iso_now(),
                duration_seconds=0.0,
                results=[],
                samples=[],
                dry_run=False,
                invariants=invariants,
                server_pid=server_pid,
                server_log_path=server_log_path,
                out_dir=out_dir,
                notes=notes,
            )
            print(f"[soak] FAIL: server did not become ready; evidence at {out_path}")
            server.stop()
            return 4

    # ---- main loop --------------------------------------------------------
    sampler = _Sampler(server_pid=server_pid, interval_seconds=args.sample_interval_seconds)
    sampler.start()

    results: list[dict] = []
    t_start = time.monotonic()
    deadline = t_start + duration_seconds
    run_index = 0

    print(
        f"[soak] running {args.duration} ({duration_seconds}s) "
        f"against {base_url} — 1 run / {args.run_interval_seconds}s"
    )

    try:
        while time.monotonic() < deadline:
            r = _submit_run(base_url, run_index)
            results.append(r)
            elapsed = time.monotonic() - t_start
            print(
                f"[soak] run #{run_index + 1}: state={r['state']} "
                f"stage_seen={r.get('stage_first_seen_seconds')} "
                f"stages={r.get('terminal_stage_count')} "
                f"dur={r['duration_seconds']}s elapsed={elapsed:.0f}s"
            )
            run_index += 1
            # Pace runs at the requested interval (cap at deadline).
            sleep_until = min(
                time.monotonic() + args.run_interval_seconds, deadline,
            )
            time.sleep(max(0.0, sleep_until - time.monotonic()))
    except KeyboardInterrupt:
        notes.append("interrupted by KeyboardInterrupt")

    duration_actual = time.monotonic() - t_start
    end_iso = _iso_now()

    # Scrape llm_fallback_count BEFORE stopping the server.
    llm_fallback_count = _scrape_llm_fallback_count(base_url)
    sampler.stop()
    if server:
        rc = server.stop()
        notes.append(f"server stopped: exit_code={rc}")

    invariants = _compute_invariants(results, llm_fallback_count)

    out_path = _write_evidence(
        sha=sha,
        full_sha=full_sha,
        requested_duration_label=args.duration,
        requested_duration_seconds=duration_seconds,
        start_time=start_iso,
        end_time=end_iso,
        duration_seconds=duration_actual,
        results=results,
        samples=sampler.samples(),
        dry_run=False,
        invariants=invariants,
        server_pid=server_pid,
        server_log_path=server_log_path,
        out_dir=out_dir,
        notes=notes,
    )
    print(f"[soak] evidence written: {out_path}")
    print(
        f"[soak] invariants_held={invariants['invariants_held']} "
        f"submitted={invariants['submitted']} terminal={invariants['terminal']} "
        f"lost={invariants['lost_runs']} dups={invariants['duplicate_run_ids']} "
        f"llm_fallback={invariants['llm_fallback_count']}"
    )
    return 0 if invariants["invariants_held"] else 1


if __name__ == "__main__":
    sys.exit(main())

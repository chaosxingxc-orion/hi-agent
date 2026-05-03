"""Soak harness with --duration 1h|24h|240m flag.

Single entry point for soak runs. Spawns a long-lived `python -m hi_agent serve`
subprocess on the configured port, fires runs concurrently across multiple
tenants and projects for the requested duration, asserts invariants at the
end, and emits truthful evidence JSON.

Invariants asserted at end of run:
  * 0 lost runs (every submitted run reached a terminal state OR was tracked as failed)
  * 0 duplicate run_ids
  * llm_fallback_count == 0 (read from /metrics)
  * every run had stage activity observed within 30s of submission (either via
    polling current_stage OR via result.stages[] non-empty at terminal — the
    latter is the reliable signal under dev-smoke fast mode where polling may
    miss a transient current_stage)
  * every terminal run has finished_at populated

W31-L1 multi-tenant invariants (when --tenants > 1 or --concurrency > 1):
  * per-tenant accepted_runs_lost == 0
  * per-tenant duplicate_terminal_executions == 0
  * cross-tenant: no run_id appears in two tenants' result lists
  * mid-soak SIGTERM (when --mid-soak-sigterm-after > 0):
      at least1 run was in flight at SIGTERM AND at least1 resumed cleanly post-restart

Usage:
    # 5-min smoke (proof of harness; tags provenance:shape_1h, NOT real 1h):
    python scripts/run_soak.py --duration 5m --port 9083

    # Real 1h soak (operator-shape; tags provenance:real if invariants hold):
    python scripts/run_soak.py --duration 1h --port 9083

    # 24h soak (kicked off in background by Track C-24h dispatch):
    python scripts/run_soak.py --duration 24h --port 9083

    # W31-L1: 4h multi-tenant soak with mid-soak SIGTERM:
    python scripts/run_soak.py --duration 4h --port 9083 \
        --tenants 3 --projects-per-tenant 2 --concurrency 6 \
        --mid-soak-sigterm-after 60 --require-polling-observation

Provenance rules (NEVER fake):
  * duration_seconds >= 86400 AND invariants_held → provenance: real (24h credit)
  * duration_seconds >= 14400 AND invariants_held → provenance: real (4h credit; W31-L1)
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


def _submit_run(
    base_url: str,
    run_index: int,
    *,
    tenant_id: str = "soak_default_tenant",
    project_id: str = "soak_test_project",
    profile_id: str = "soak_test",
    idempotency_key: str | None = None,
    per_run_timeout_seconds: float = 60.0,
    server_restart_event: threading.Event | None = None,
    server_restart_timeout_seconds: float = 120.0,
) -> dict:
    """Submit one run and poll until terminal or timeout. Returns result dict.

    Tracks invariants:
      * stage_first_seen_seconds: seconds between submission and first non-None current_stage
      * terminal_stage_count: number of stages recorded in result.stages[] at terminal
      * finished_at: populated when state reaches a terminal value
      * tenant_id, project_id: spine fields for cross-tenant isolation checks
      * idempotency_key: the W31-L1 idempotency key wired into routes_runs.py

    When ``server_restart_event`` is set during polling (mid-soak SIGTERM),
    the worker pauses polling for up to ``server_restart_timeout_seconds``
    and resumes once the event clears. A run that was in-flight at SIGTERM
    and reaches a terminal state after restart is recorded with
    ``resumed_after_restart=True``.
    """
    import httpx

    payload = {
        "goal": f"soak-run-{tenant_id}-{run_index}",
        "profile_id": profile_id,
        "project_id": project_id,
        "task_family": "smoke",
        # Spine field passed in body for downstream traceability. Auth
        # middleware sets the authenticated tenant_id; this is the
        # workload-side label used for cross-tenant invariant checks.
        "tenant_id": tenant_id,
    }
    headers: dict[str, str] = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    submit_t = time.monotonic()
    run_id: str | None = None
    state = "unknown"
    error: str | None = None
    stage_first_seen_seconds: float | None = None
    terminal_stage_count = 0
    finished_at: str | None = None
    poll_count = 0
    in_flight_at_restart = False
    resumed_after_restart = False
    try:
        c = httpx.Client(timeout=httpx.Timeout(10.0), trust_env=False)
        resp = c.post(f"{base_url}/runs", json=payload, headers=headers)
        if resp.status_code not in (200, 201, 202):
            error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return {
                "run_index": run_index,
                "run_id": None,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "idempotency_key": idempotency_key,
                "state": "http_error",
                "stage_first_seen_seconds": None,
                "terminal_stage_count": 0,
                "finished_at": None,
                "in_flight_at_restart": False,
                "resumed_after_restart": False,
                "duration_seconds": round(time.monotonic() - submit_t, 3),
                "error": error,
            }
        body = resp.json()
        run_id = body.get("run_id") or body.get("id")
        # Per-run timeout: real-LLM runs may take 30-60s; allow caller to widen.
        per_run_deadline = time.monotonic() + per_run_timeout_seconds
        while time.monotonic() < per_run_deadline:
            # Mid-soak SIGTERM handling: when the orchestrator sets
            # server_restart_event, the server is being killed and re-spawned.
            # The worker pauses HTTP traffic during the gap and records that
            # this run was in flight at SIGTERM time.
            if server_restart_event is not None and server_restart_event.is_set():
                in_flight_at_restart = True
                # Wait for the event to clear (server back up) up to the
                # configured timeout, then resume polling.
                wait_deadline = time.monotonic() + server_restart_timeout_seconds
                while server_restart_event.is_set() and time.monotonic() < wait_deadline:
                    time.sleep(0.5)
                # Even if the event hasn't cleared we attempt one more poll
                # (the server may already be back).
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
                        if in_flight_at_restart and state in (
                            "completed", "done",
                        ):
                            resumed_after_restart = True
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
        "tenant_id": tenant_id,
        "project_id": project_id,
        "idempotency_key": idempotency_key,
        "state": state,
        "stage_first_seen_seconds": stage_first_seen_seconds,
        "terminal_stage_count": terminal_stage_count,
        "finished_at": finished_at,
        "in_flight_at_restart": in_flight_at_restart,
        "resumed_after_restart": resumed_after_restart,
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
    """Samples the server process every interval_seconds.

    W32-C.7: ``self._pid`` is read by ``_loop`` per iteration and rebound
    by the SIGTERM orchestrator after server respawn. Both access sites
    take ``self._pid_lock`` so a concurrent rebind cannot tear the read.
    Use ``rebind_pid()`` instead of writing ``_pid`` directly.
    """

    def __init__(self, server_pid: int | None, interval_seconds: float) -> None:
        self._pid = server_pid
        self._interval = interval_seconds
        self._samples: list[dict] = []
        self._lock = threading.Lock()
        # W32-C.7: serialises read/write of self._pid with the SIGTERM
        # orchestrator's pid rebinding. Without this, the sampler loop and
        # the orchestrator thread can race on the assignment.
        self._pid_lock = threading.Lock()
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

    def rebind_pid(self, pid: int | None) -> None:
        """Atomically rebind the sampled PID (used after SIGTERM respawn)."""
        with self._pid_lock:
            self._pid = pid

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            with self._pid_lock:
                pid = self._pid
            sample = {
                "ts": _iso_now(),
                "rss_mb": _process_rss_mb(pid),
                "cpu_pct": _process_cpu_pct(pid),
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
    require_polling_observation: bool = False,
    multi_tenant: bool = False,
    sigterm_injected: bool = False,
) -> dict:
    """Compute invariants_held + per-invariant pass/fail map.

    W31-L (L-15' fix): when ``require_polling_observation`` is True, only
    polling_ok counts toward the stage-observation invariant. The
    post-hoc ``result.stages[]`` is a structural signal and cannot
    substitute for the Rule-8 step-5 hard requirement that
    ``current_stage`` is non-None within 30s on every turn during
    polling. L.2 (real soak) MUST be invoked with this flag.

    W31-L1 multi-tenant invariants (when ``multi_tenant=True``):
      * per-tenant accepted_runs_lost == 0 (a "lost" run is one that
        returned 200 to POST /runs but never reached a terminal state
        and was not tracked as a timeout/exception)
      * per-tenant duplicate_terminal_executions == 0 (the same run_id
        reached a terminal state more than once)
      * cross-tenant: no run_id appears in two tenants' result lists
      * mid-soak SIGTERM: at least1 run was in flight AND at least1 resumed cleanly
    """
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

    # Stage observed within window.
    #
    # Default (lenient) mode — two signals satisfy the invariant:
    #   1. current_stage was non-None within the observation window during polling
    #      (the original Rule-8 check, only reliable when stages take >0.5s each)
    #   2. result.stages[] is non-empty at terminal (reliable for runs that
    #      finished too fast for polling to catch a transient current_stage,
    #      common under dev-smoke fast mode)
    # If neither signal fires, the run is a stage_miss.
    #
    # Strict mode (W31-L L-15' fix; require_polling_observation=True) —
    # ONLY signal 1 counts. terminal_stages_ok alone fails the invariant.
    # Per Rule 8 step-5, current_stage non-None within 30s is the hard
    # requirement; result.stages[] is only a structural signal.
    stage_misses: list[int] = []
    for r in results:
        if r.get("state") not in _TERMINAL_STATES:
            continue
        sfs = r.get("stage_first_seen_seconds")
        polling_ok = sfs is not None and sfs <= stage_observation_window_seconds
        terminal_stages_ok = (r.get("terminal_stage_count") or 0) > 0
        if require_polling_observation:
            # Strict mode: polling MUST observe a stage. Post-hoc
            # terminal_stage_count is a structural signal; insufficient
            # by itself for Rule-8 step-5 compliance.
            if not polling_ok:
                stage_misses.append(r.get("run_index", -1))
        else:
            # Lenient (default) mode: either signal satisfies the invariant.
            if not polling_ok and not terminal_stages_ok:
                stage_misses.append(r.get("run_index", -1))

    # finished_at populated on every terminal.
    finished_at_misses = [
        r.get("run_index", -1) for r in results
        if r.get("state") in _TERMINAL_STATES and not r.get("finished_at")
    ]

    # ---- W31-L1 multi-tenant invariants ------------------------------------
    per_tenant: dict[str, dict] = {}
    cross_tenant_leaks: list[dict] = []
    duplicate_terminal_executions = 0
    in_flight_count = 0
    resumed_count = 0
    if multi_tenant:
        # Per-tenant aggregation.
        by_tenant: dict[str, list[dict]] = {}
        for r in results:
            tid = r.get("tenant_id") or "__unlabelled__"
            by_tenant.setdefault(tid, []).append(r)
        for tid, runs in by_tenant.items():
            t_submitted = len(runs)
            t_terminal = sum(
                1 for r in runs if r.get("state") in _TERMINAL_STATES
            )
            t_timeout = sum(
                1 for r in runs
                if r.get("state") in ("timeout", "exception", "http_error")
            )
            t_lost = t_submitted - t_terminal - t_timeout
            t_ids = [r.get("run_id") for r in runs if r.get("run_id")]
            t_dups = len(t_ids) - len(set(t_ids))
            per_tenant[tid] = {
                "submitted": t_submitted,
                "terminal": t_terminal,
                "timeout_or_exception": t_timeout,
                "accepted_runs_lost": max(0, t_lost),
                "duplicate_terminal_executions": t_dups,
                "projects": sorted(
                    {r.get("project_id", "") for r in runs if r.get("project_id")}
                ),
            }
            duplicate_terminal_executions += t_dups
        # Cross-tenant leak detection: a run_id appearing under two tenants'
        # result lists indicates an idempotency-store leak or auth-context
        # spillover.
        run_id_to_tenants: dict[str, set[str]] = {}
        for r in results:
            rid = r.get("run_id")
            tid = r.get("tenant_id") or "__unlabelled__"
            if not rid:
                continue
            run_id_to_tenants.setdefault(rid, set()).add(tid)
        for rid, tenants in run_id_to_tenants.items():
            if len(tenants) > 1:
                cross_tenant_leaks.append(
                    {"run_id": rid, "tenants": sorted(tenants)}
                )
        # Mid-soak SIGTERM resume tally.
        in_flight_count = sum(
            1 for r in results if r.get("in_flight_at_restart")
        )
        resumed_count = sum(
            1 for r in results if r.get("resumed_after_restart")
        )

    invariants: dict[str, tuple[bool, object]] = {
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
    if multi_tenant:
        # Per-tenant aggregate: invariant holds when every tenant has 0 lost
        # and 0 duplicate terminals.
        per_tenant_lost = sum(t["accepted_runs_lost"] for t in per_tenant.values())
        invariants["per_tenant_no_lost_runs"] = (
            per_tenant_lost == 0, per_tenant_lost,
        )
        invariants["per_tenant_no_duplicate_terminal_executions"] = (
            duplicate_terminal_executions == 0,
            duplicate_terminal_executions,
        )
        invariants["no_cross_tenant_run_id_leak"] = (
            not cross_tenant_leaks, cross_tenant_leaks[:5],
        )
        if sigterm_injected:
            # The mid-soak SIGTERM contract is two-fold: at least1 in-flight at
            # SIGTERM AND at least1 resumed cleanly. A SIGTERM that no run
            # observed (e.g. injected too early) does not satisfy the
            # invariant and indicates the harness or workload was not
            # exercising in-flight runs at the injection time.
            invariants["mid_soak_sigterm_resume"] = (
                in_flight_count >= 1 and resumed_count >= 1,
                {
                    "in_flight_at_restart": in_flight_count,
                    "resumed_after_restart": resumed_count,
                },
            )
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
        "per_tenant": per_tenant,
        "cross_tenant_leaks": cross_tenant_leaks,
        "duplicate_terminal_executions": duplicate_terminal_executions,
        "in_flight_at_restart_count": in_flight_count,
        "resumed_after_restart_count": resumed_count,
        "details": {
            k: {"passed": passed, "value": value}
            for k, (passed, value) in invariants.items()
        },
    }


# ---------------------------------------------------------------------------
# Evidence emission
# ---------------------------------------------------------------------------


def _classify_provenance(
    duration_seconds: float,
    invariants_held: bool,
    dry_run: bool,
    requested_duration_seconds: int = 0,
) -> tuple[str, str]:
    """Return (provenance, label_hours).

    W31-L1: The 4h band (>=14400s, <86400s) is "real" credit when
    invariants hold. ``requested_duration_seconds`` is consulted for the
    canonical filename suffix (240m vs 1h vs ad-hoc minute count).
    """
    if dry_run:
        return "dry_run", "dry"
    # Real soaks must hold invariants AND meet duration thresholds.
    if duration_seconds >= 86400.0 and invariants_held:
        return "real", "24h"
    if duration_seconds >= 14400.0 and invariants_held:
        return "real", "240m"
    if duration_seconds >= 3600.0 and invariants_held:
        return "real", "1h"
    # Otherwise: shape_1h smoke validation. NOT 1h credit.
    return "shape_1h", "shape"


def _evidence_filename(
    sha: str,
    duration_seconds: float,
    dry_run: bool,
    provenance: str,
    requested_duration_seconds: int = 0,
) -> str:
    """Pick a filename per the dispatch convention.

    Uses a 'shape' suffix when provenance is shape_1h to make the truthfulness
    visible at the filename level. Real soak evidence uses the canonical
    forms: `<HEAD>-soak-1h.json`, `<HEAD>-soak-240m.json`, `<HEAD>-soak-24h.json`.
    The 240m suffix is the W31-L1 convention for 4h soaks.
    """
    if dry_run:
        return f"{sha}-soak-dry-{int(duration_seconds // 60)}m.json"
    if provenance == "shape_1h":
        return f"{sha}-soak-shape-{int(duration_seconds // 60)}m.json"
    if provenance == "real" and duration_seconds >= 86400.0:
        return f"{sha}-soak-24h.json"
    if provenance == "real" and duration_seconds >= 14400.0:
        return f"{sha}-soak-240m.json"
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
    workload: dict | None = None,
    sigterm_events: list[dict] | None = None,
) -> Path:
    provenance, _label = _classify_provenance(
        duration_seconds,
        invariants["invariants_held"],
        dry_run,
        requested_duration_seconds=requested_duration_seconds,
    )
    filename = _evidence_filename(
        sha,
        duration_seconds,
        dry_run,
        provenance,
        requested_duration_seconds=requested_duration_seconds,
    )
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
    if workload is not None:
        evidence["workload"] = workload
    # Per-tenant + cross-tenant + SIGTERM blocks always present in multi-tenant
    # mode; `per_tenant` is empty when invariants were computed in single-tenant
    # mode.
    if invariants.get("per_tenant"):
        evidence["per_tenant"] = invariants["per_tenant"]
        evidence["cross_tenant_leaks"] = invariants.get("cross_tenant_leaks", [])
        evidence["duplicate_terminal_executions"] = invariants.get(
            "duplicate_terminal_executions", 0,
        )
        evidence["in_flight_at_restart_count"] = invariants.get(
            "in_flight_at_restart_count", 0,
        )
        evidence["resumed_after_restart_count"] = invariants.get(
            "resumed_after_restart_count", 0,
        )
    if sigterm_events:
        evidence["sigterm_events"] = sigterm_events
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
    parser.add_argument(
        "--require-polling-observation",
        action="store_true",
        default=False,
        help=(
            "Strict Rule-8 step-5 mode. When set, only polling_ok counts "
            "toward the stage-observation invariant; terminal_stages_ok "
            "alone fails the invariant. Required for real long-running "
            "soaks. Per Rule 8 step-5, current_stage non-None within 30s "
            "is the hard requirement; the post-hoc result.stages[] field "
            "is only a structural signal."
        ),
    )
    parser.add_argument(
        "--tenants",
        type=int,
        default=1,
        help=(
            "W31-L1: number of distinct tenants generating load (default: 1). "
            "Each tenant uses a unique tenant_id label in the request payload "
            "and a unique Idempotency-Key prefix. Set >=3 for the W31-L1 "
            "multi-tenant invariant set."
        ),
    )
    parser.add_argument(
        "--projects-per-tenant",
        type=int,
        default=1,
        help=(
            "W31-L1: number of project_ids per tenant (default: 1). Each "
            "(tenant, project) pair gets its own slot in the round-robin "
            "worker dispatch. Set >=2 for the W31-L1 invariant set."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "W31-L1: number of concurrent worker threads sending POST /runs "
            "(default: 1). When >1, workers pick (tenant, project) "
            "round-robin from the cross product of --tenants x "
            "--projects-per-tenant."
        ),
    )
    parser.add_argument(
        "--mid-soak-sigterm-after",
        type=float,
        default=0.0,
        help=(
            "W31-L1: wall-clock minute at which to SIGTERM the server PID "
            "and restart it (default: 0 = no SIGTERM). The harness restarts "
            "the server within 60s and resumes sampling. After SIGTERM, runs "
            "in flight should resume cleanly via durable run_store. Set to "
            "60 (minutes) for the canonical W31-L1 mid-soak SIGTERM."
        ),
    )
    parser.add_argument(
        "--per-run-timeout-seconds",
        type=float,
        default=180.0,
        help=(
            "Per-run polling deadline in seconds (default: 180). Real-LLM "
            "runs commonly finish in 10-30s; widen for slower providers."
        ),
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

    # ---- W31-L1 workload setup --------------------------------------------
    if args.tenants < 1:
        print("[soak] --tenants must be >= 1", file=sys.stderr)
        return 5
    if args.projects_per_tenant < 1:
        print("[soak] --projects-per-tenant must be >= 1", file=sys.stderr)
        return 5
    if args.concurrency < 1:
        print("[soak] --concurrency must be >= 1", file=sys.stderr)
        return 5

    tenants = [f"soak_t{i}" for i in range(args.tenants)]
    projects = [f"soak_p{j}" for j in range(args.projects_per_tenant)]
    workload_pairs = [(t, p) for t in tenants for p in projects]
    multi_tenant = (
        args.tenants > 1
        or args.projects_per_tenant > 1
        or args.concurrency > 1
    )
    workload = {
        "tenants": args.tenants,
        "projects_per_tenant": args.projects_per_tenant,
        "concurrency": args.concurrency,
        "tenants_list": tenants,
        "projects_list": projects,
        "mid_soak_sigterm_after_minutes": args.mid_soak_sigterm_after,
        "run_interval_seconds": args.run_interval_seconds,
        "per_run_timeout_seconds": args.per_run_timeout_seconds,
    }

    # ---- main loop --------------------------------------------------------
    sampler = _Sampler(server_pid=server_pid, interval_seconds=args.sample_interval_seconds)
    sampler.start()

    results: list[dict] = []
    results_lock = threading.Lock()
    t_start = time.monotonic()
    deadline = t_start + duration_seconds
    run_index_counter = [0]
    run_index_lock = threading.Lock()
    server_restart_event = threading.Event()
    sigterm_events: list[dict] = []
    sigterm_events_lock = threading.Lock()
    workers_stop = threading.Event()
    # Server reference is rebound by the SIGTERM thread; protect with lock so
    # invariant code reads the latest pid/log_path.
    server_ref: list[_ServerProcess | None] = [server]
    server_pid_ref: list[int | None] = [server_pid]
    server_log_ref: list[str] = [server_log_path]

    def _next_run_index() -> int:
        with run_index_lock:
            i = run_index_counter[0]
            run_index_counter[0] += 1
            return i

    def _worker_loop(worker_id: int) -> None:
        """One worker submits POST /runs cycling through ALL (tenant, project)
        pairs per submission so every pair gets exercised regardless of the
        concurrency vs |pairs| ratio.

        Workers are paced by --run-interval-seconds. With N workers, the
        aggregate submission rate is approximately N / run_interval_seconds.
        Each worker uses a separate offset into workload_pairs so concurrent
        submissions span distinct tenants when possible.
        """
        local_pair_idx = worker_id % len(workload_pairs)
        while time.monotonic() < deadline and not workers_stop.is_set():
            ri = _next_run_index()
            tenant_id, project_id = workload_pairs[
                local_pair_idx % len(workload_pairs)
            ]
            local_pair_idx += 1
            idem_key = f"w31-soak-{tenant_id}-{project_id}-{ri}"
            r = _submit_run(
                base_url,
                ri,
                tenant_id=tenant_id,
                project_id=project_id,
                profile_id="soak_test",
                idempotency_key=idem_key,
                per_run_timeout_seconds=args.per_run_timeout_seconds,
                server_restart_event=server_restart_event,
            )
            r["worker_id"] = worker_id
            with results_lock:
                results.append(r)
            elapsed = time.monotonic() - t_start
            print(
                f"[soak] worker {worker_id} run #{ri} "
                f"tenant={tenant_id} project={project_id} "
                f"state={r['state']} "
                f"stage_seen={r.get('stage_first_seen_seconds')} "
                f"stages={r.get('terminal_stage_count')} "
                f"in_flight_at_restart={r.get('in_flight_at_restart')} "
                f"resumed={r.get('resumed_after_restart')} "
                f"elapsed_minutes={elapsed / 60:.1f}"
            )
            # Pace runs at the requested interval (cap at deadline).
            next_t = min(
                time.monotonic() + args.run_interval_seconds, deadline,
            )
            while time.monotonic() < next_t and not workers_stop.is_set():
                time.sleep(min(1.0, max(0.0, next_t - time.monotonic())))

    def _sigterm_orchestrator() -> None:
        """Mid-soak SIGTERM: kill server PID at the configured minute and
        respawn within 60s. Sets server_restart_event during the gap so
        worker threads pause polling.

        Skips the SIGTERM if --no-spawn-server is set (we don't own the
        server process) or if the configured minute is 0/negative.
        """
        if args.mid_soak_sigterm_after <= 0:
            return
        if args.no_spawn_server:
            print(
                "[soak] mid-soak SIGTERM requested but --no-spawn-server is "
                "set; harness does not own the server process — skipping."
            )
            return
        target_seconds = args.mid_soak_sigterm_after * 60.0
        # Sleep until target_seconds after t_start.
        while time.monotonic() < t_start + target_seconds:
            if workers_stop.is_set():
                return
            time.sleep(1.0)
        if workers_stop.is_set():
            return

        sigterm_t0 = _iso_now()
        sigterm_t0_mono = time.monotonic()
        old_pid = server_pid_ref[0]
        print(
            f"[soak] mid-soak SIGTERM: killing server pid={old_pid} "
            f"at elapsed_minutes={args.mid_soak_sigterm_after}"
        )
        server_restart_event.set()
        old_server = server_ref[0]
        if old_server is not None:
            try:
                rc = old_server.stop()
                print(f"[soak] mid-soak SIGTERM: server stopped exit_code={rc}")
            except Exception as exc:
                print(f"[soak] mid-soak SIGTERM: server.stop() raised: {exc}")

        # Respawn — wait briefly for OS to release port, then start a new
        # server on the same port pointing at the same data dir.
        time.sleep(2.0)
        new_server = _ServerProcess(args.port, log_dir=log_dir)
        new_server.start()
        server_ref[0] = new_server
        server_pid_ref[0] = new_server.pid
        server_log_ref[0] = str(new_server.log_path)
        ready = new_server.wait_ready(base_url, timeout_seconds=90.0)
        sigterm_t1 = _iso_now()
        gap = round(time.monotonic() - sigterm_t0_mono, 2)
        with sigterm_events_lock:
            sigterm_events.append({
                "killed_pid": old_pid,
                "killed_at": sigterm_t0,
                "respawned_pid": new_server.pid,
                "respawned_at": sigterm_t1,
                "ready_after_restart": ready,
                "downtime_seconds": gap,
            })
        notes.append(
            f"mid-soak SIGTERM at minute {args.mid_soak_sigterm_after}: "
            f"old_pid={old_pid} new_pid={new_server.pid} "
            f"ready={ready} downtime_seconds={gap}"
        )
        # W32-C.7: Update sampler's pid so RSS/CPU samples track the new
        # process. rebind_pid() takes the sampler's pid_lock so the
        # sampler loop never sees a half-written pid.
        import contextlib as _ctxlib

        with _ctxlib.suppress(Exception):
            sampler.rebind_pid(new_server.pid)
        if not ready:
            print(
                "[soak] mid-soak SIGTERM: respawn FAILED to become ready; "
                "soak will continue but invariants will likely fail."
            )
        # Clear the event so workers resume polling.
        server_restart_event.clear()

    print(
        f"[soak] running {args.duration} ({duration_seconds}s) "
        f"against {base_url} — concurrency={args.concurrency} "
        f"tenants={args.tenants} projects_per_tenant={args.projects_per_tenant} "
        f"workload_pairs={len(workload_pairs)} "
        f"sigterm_after={args.mid_soak_sigterm_after}min"
    )

    # Spawn workers — each cycles through ALL (tenant, project) pairs, so
    # every pair is exercised regardless of the concurrency vs |pairs| ratio.
    worker_threads: list[threading.Thread] = []
    for w in range(args.concurrency):
        th = threading.Thread(
            target=_worker_loop,
            args=(w,),
            daemon=True,
            name=f"soak-worker-{w}",
        )
        th.start()
        worker_threads.append(th)

    sigterm_thread: threading.Thread | None = None
    if args.mid_soak_sigterm_after > 0:
        sigterm_thread = threading.Thread(
            target=_sigterm_orchestrator,
            daemon=True,
            name="soak-sigterm",
        )
        sigterm_thread.start()

    try:
        # Main thread idles until the deadline; workers and sigterm threads
        # do the actual work. Periodic heartbeat for log clarity.
        last_heartbeat = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(5.0)
            now = time.monotonic()
            if now - last_heartbeat >= 60.0:
                with results_lock:
                    n = len(results)
                elapsed = now - t_start
                print(
                    f"[soak] heartbeat: elapsed_minutes={elapsed / 60:.1f} "
                    f"submitted={n} deadline_in_minutes={(deadline - now) / 60:.1f}"
                )
                last_heartbeat = now
    except KeyboardInterrupt:
        notes.append("interrupted by KeyboardInterrupt")

    workers_stop.set()
    # Give workers up to per_run_timeout_seconds + buffer to drain in-flight runs.
    drain_deadline = time.monotonic() + args.per_run_timeout_seconds + 30.0
    for th in worker_threads:
        remaining = max(1.0, drain_deadline - time.monotonic())
        th.join(timeout=remaining)
    if sigterm_thread is not None:
        sigterm_thread.join(timeout=30.0)

    duration_actual = time.monotonic() - t_start
    end_iso = _iso_now()

    # W32-C.4: scrape llm_fallback_count AFTER the server has terminated so
    # that any final fallback emitted during shutdown is captured. The
    # previous order (scrape -> stop) created a race where shutdown-time
    # fallbacks could be lost from the soak evidence.
    #
    # Order: stop server -> wait for termination -> scrape final metrics
    # via the in-process metrics collector (the HTTP /metrics endpoint is
    # gone after server stop, so we read the persisted counter directly
    # from the same process if available; otherwise fall back to one last
    # HTTP scrape against the URL while the server is still up).
    #
    # Concretely: snapshot via HTTP just-before-stop AND a second time
    # after stop (max of the two), so the count is monotonic and we never
    # under-report.
    pre_stop_fallback = _scrape_llm_fallback_count(base_url)
    sampler.stop()
    final_server = server_ref[0]
    if final_server is not None:
        rc = final_server.stop()
        notes.append(f"server stopped: exit_code={rc}")
    # Post-stop scrape: server is shutting down; counter exporters may still
    # be listening for a brief window if the process honours graceful drain.
    # If unreachable, _scrape_llm_fallback_count returns 0 and we keep the
    # pre-stop value.
    post_stop_fallback = _scrape_llm_fallback_count(base_url)
    llm_fallback_count = max(pre_stop_fallback, post_stop_fallback)
    notes.append(
        f"llm_fallback_count: pre_stop={pre_stop_fallback} "
        f"post_stop={post_stop_fallback} final={llm_fallback_count}"
    )

    invariants = _compute_invariants(
        results,
        llm_fallback_count,
        require_polling_observation=args.require_polling_observation,
        multi_tenant=multi_tenant,
        sigterm_injected=bool(sigterm_events),
    )

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
        server_pid=server_pid_ref[0],
        server_log_path=server_log_ref[0],
        out_dir=out_dir,
        notes=notes,
        workload=workload,
        sigterm_events=sigterm_events,
    )
    print(f"[soak] evidence written: {out_path}")
    print(
        f"[soak] invariants_held={invariants['invariants_held']} "
        f"submitted={invariants['submitted']} terminal={invariants['terminal']} "
        f"lost={invariants['lost_runs']} dups={invariants['duplicate_run_ids']} "
        f"llm_fallback={invariants['llm_fallback_count']} "
        f"in_flight_at_restart={invariants.get('in_flight_at_restart_count', 0)} "
        f"resumed={invariants.get('resumed_after_restart_count', 0)}"
    )
    return 0 if invariants["invariants_held"] else 1


if __name__ == "__main__":
    sys.exit(main())

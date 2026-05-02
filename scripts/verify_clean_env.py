#!/usr/bin/env python
"""Portable clean-environment verification wrapper.

Runs the full Wave test bundle in a clean temp directory -- no repo-internal
.pytest_tmp or .pytest_cache pollution.

Exit 0: all tests passed (or skipped).
Exit 1: tests failed or pytest could not be collected.
Exit 2: pre-flight permission check failed.

Usage::

    # Default: offline-safe bundle (excludes live_api, external_llm, network, requires_secret)
    python scripts/verify_clean_env.py

    # Smoke profile: small W5 subset, fast
    python scripts/verify_clean_env.py --profile smoke-w5

    # Full release bundle (includes live API tests)
    python scripts/verify_clean_env.py --profile release

    # Custom bundle from a file
    python scripts/verify_clean_env.py --profile custom --bundle /tmp/my_bundle.txt

    # Custom paths (for CI or restricted environments)
    python scripts/verify_clean_env.py \\
        --basetemp /tmp/hi_agent_pytest \\
        --cache-dir /tmp/hi_agent_cache \\
        --json-report docs/delivery/<sha>-clean-env.json

Environment variables (lower priority than CLI args):
    HI_AGENT_PYTEST_TEMPROOT   override basetemp
    HI_AGENT_PYTEST_CACHE_DIR  override cache-dir
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.metadata
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]  expiry_wave: permanent
    except ImportError:
        tomllib = None  # type: ignore[assignment]  expiry_wave: permanent

ROOT = Path(__file__).resolve().parent.parent

_PROFILES_PATH = ROOT / "tests" / "profiles.toml"


def _load_profiles() -> dict:
    """Load test profiles from tests/profiles.toml if tomllib is available."""
    if tomllib is None or not _PROFILES_PATH.exists():
        return {}
    try:
        with open(_PROFILES_PATH, "rb") as f:
            data = tomllib.load(f)
        return data.get("profiles", {})
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# Wave test bundle -- paths relative to repo root.
# Keep this list intact; additions/removals are tracked separately.
# ---------------------------------------------------------------------------
WAVE_TEST_BUNDLE: list[str] = [
    "tests/unit",
    "tests/integration",
    "tests/contract",
    "tests/security",
    "tests/agent_kernel",
    "tests/runtime_adapter",
    "tests/server",
]

# ---------------------------------------------------------------------------
# Smoke-W5 bundle -- small subset for fast pre-flight checks.
# ---------------------------------------------------------------------------
SMOKE_W5_BUNDLE: list[str] = [
    "tests/unit/test_misc_defects.py",
    "tests/unit/test_json_config_loader_base_url.py",
    "tests/unit/test_contracts.py",
    "tests/unit/test_posture.py",
    "tests/unit/test_rule6_sweep.py",
    "tests/unit/test_gate_protocol.py",
    "tests/unit/test_run_store.py",
    "tests/unit/test_idempotency.py",
    "tests/unit/test_context_manager.py",
    "tests/unit/test_memory_lifecycle.py",
]

# ---------------------------------------------------------------------------
# default-offline profile -- unit + contract + security + agent_kernel only.
# Excludes tests/integration (slow, 419 files), tests/runtime_adapter,
# tests/server.  Target runtime: <= 10 min.  Use case: developer health check
# before push.
# ---------------------------------------------------------------------------
_DEFAULT_OFFLINE_PATHS: list[str] = [
    "tests/unit",
    "tests/contract",
    "tests/security",
    "tests/agent_kernel",
]

# ---------------------------------------------------------------------------
# nightly profile -- full WAVE_TEST_BUNDLE + e2e + perf + characterization +
# golden.  Paths that do not exist on disk are silently skipped by
# _filter_existing().  Target runtime: unlimited.  Use case: scheduled nightly
# full coverage.
# ---------------------------------------------------------------------------
_NIGHTLY_PATHS: list[str] = [
    *WAVE_TEST_BUNDLE,
    "tests/e2e",
    "tests/perf",
    "tests/characterization",
    "tests/golden",
]

# Markers excluded from the default-offline profile
_OFFLINE_EXCLUDED_MARKERS: list[str] = [
    "live_api",
    "external_llm",
    "network",
    "requires_secret",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Wave test bundle in a portable clean environment.",
    )
    parser.add_argument(
        "--profile",
        choices=[
            "smoke-w5",
            "smoke",
            "default-offline",
            "release",
            "nightly",
            "live_api",
            "prod_e2e",
            "soak",
            "chaos",
            "custom",
        ],
        default="default-offline",
        help=(
            "Bundle profile to use. "
            "'default-offline' runs unit/contract/security/agent_kernel only "
            "(<=10 min, developer health check). "
            "'release' runs the full WAVE_TEST_BUNDLE with no marker exclusions "
            "(<=30 min, pre-release regression). "
            "'nightly' runs release paths plus e2e/perf/characterization/golden "
            "(unlimited, scheduled nightly). "
            "'smoke' / 'smoke-w5' runs a small subset for fast pre-flight. "
            "'live_api' includes real-network/LLM tests. "
            "'prod_e2e' is the full production E2E gate. "
            "'soak' runs perf tests. "
            "'chaos' runs chaos-matrix tests. "
            "'custom' reads test list from --bundle PATH."
        ),
    )
    parser.add_argument(
        "--basetemp",
        metavar="PATH",
        default=None,
        help=(
            "Override pytest basetemp directory. "
            "Priority: CLI > HI_AGENT_PYTEST_TEMPROOT env var > tempfile.mkdtemp()."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        metavar="PATH",
        default=None,
        help=(
            "Override pytest cache directory. "
            "Priority: CLI > HI_AGENT_PYTEST_CACHE_DIR env var > tempfile.mkdtemp()."
        ),
    )
    parser.add_argument(
        "--json-report",
        metavar="PATH",
        default=None,
        help="Write machine-readable evidence JSON to this path.",
    )
    parser.add_argument(
        "--no-fail-fast-env-check",
        action="store_true",
        default=False,
        help="Disable pre-flight permission checks (fail-fast is default ON).",
    )
    parser.add_argument(
        "--bundle",
        metavar="PATH",
        default=None,
        help=(
            "Read test paths from a file (one path per line) instead of the "
            "embedded WAVE_TEST_BUNDLE list. Only used with --profile custom."
        ),
    )
    return parser.parse_args()


def _resolve_dir(cli_value: str | None, env_key: str, prefix: str) -> str:
    """Return the directory path using CLI > env var > tempfile priority."""
    if cli_value is not None:
        return cli_value
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value
    return tempfile.mkdtemp(prefix=prefix)


def _preflight_check(path: str) -> bool:
    """Check read/write access to *path*. Returns True on success, False on failure.

    On failure, prints ``ENV-CHECK-FAIL: {path} {stage} {error}`` to stderr.
    """
    sentinel = Path(path) / "_preflight_check_sentinel.txt"

    # Stage 1: mkdir
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ENV-CHECK-FAIL: {path} mkdir {exc}", file=sys.stderr)
        return False

    # Stage 2: write
    try:
        sentinel.write_text("ok", encoding="utf-8")
    except OSError as exc:
        print(f"ENV-CHECK-FAIL: {path} write {exc}", file=sys.stderr)
        return False

    # Stage 3: read
    try:
        content = sentinel.read_text(encoding="utf-8")
        if content != "ok":
            print(
                f"ENV-CHECK-FAIL: {path} read content mismatch: {content!r}",
                file=sys.stderr,
            )
            return False
    except OSError as exc:
        print(f"ENV-CHECK-FAIL: {path} read {exc}", file=sys.stderr)
        return False

    # Stage 4: delete
    try:
        sentinel.unlink()
    except OSError as exc:
        print(f"ENV-CHECK-FAIL: {path} delete {exc}", file=sys.stderr)
        return False

    return True


def _git_head() -> str:
    """Return current git HEAD SHA, or 'unknown' on failure."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def _load_bundle(bundle_path: str) -> list[str]:
    """Read test paths from a file (one per line, strips blank lines and comments)."""
    lines = Path(bundle_path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _filter_existing(paths: list[str]) -> tuple[list[str], list[str]]:
    """Split paths into (existing, missing) relative to ROOT."""
    existing = []
    missing = []
    for p in paths:
        full = ROOT / p
        if full.exists():
            existing.append(p)
        else:
            missing.append(p)
    return existing, missing


def _platform_excluded_markers(excluded: list[str]) -> list[str]:
    """On non-Windows, strip 'windows_unsafe' (those tests only hang on win32)."""
    import sys
    if sys.platform != "win32":
        return [m for m in excluded if m != "windows_unsafe"]
    return excluded


def _resolve_bundle_and_marker_args(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    """Return (raw_paths, extra_pytest_args) based on the selected profile.

    Profile summary:
    - default-offline: unit/contract/security/agent_kernel only (<=10 min).
      Applies marker exclusions as a secondary filter.  Developer health check.
    - release: full WAVE_TEST_BUNDLE, no marker exclusions (<=30 min).
      Pre-release regression gate.
    - nightly: release paths + e2e/perf/characterization/golden (unlimited).
      Scheduled nightly full coverage run.
    - smoke / smoke-w5: small subset for fast pre-flight checks.
    - live_api / prod_e2e / soak / chaos: loaded from tests/profiles.toml.
    - custom: paths loaded from --bundle file.

    extra_pytest_args may include a ``-m`` marker expression for default-offline.

    Soft integration: if tests/profiles.toml cannot be loaded, falls back to
    hardcoded behavior for known profiles.
    """
    profile = args.profile

    # --- profiles.toml soft integration ------------------------------------
    # Profiles exclusively defined in profiles.toml (no hardcoded fallback).
    toml_only_profiles = {"live_api", "prod_e2e", "soak", "chaos"}
    # Profiles that have both a toml definition and a hardcoded fallback.
    toml_overlay_profiles = {"smoke", "default-offline", "release"}

    toml_profiles = _load_profiles()

    if profile in toml_only_profiles:
        if toml_profiles and profile in toml_profiles:
            p_def = toml_profiles[profile]
            raw_paths = list(p_def.get("targets", []))
            excluded = _platform_excluded_markers(p_def.get("excluded_markers", []))
            if excluded:
                marker_expr = " and ".join(f"not {m}" for m in excluded)
                extra_args: list[str] = ["-m", marker_expr]
            else:
                extra_args = []
        else:
            print(
                f"ERROR: profile '{profile}' requires tests/profiles.toml "
                "but it could not be loaded.",
                file=sys.stderr,
            )
            sys.exit(1)
        return raw_paths, extra_args

    if profile in toml_overlay_profiles and toml_profiles and profile in toml_profiles:
        p_def = toml_profiles[profile]
        raw_paths = list(p_def.get("targets", []))
        excluded = _platform_excluded_markers(p_def.get("excluded_markers", []))
        if excluded:
            marker_expr = " and ".join(f"not {m}" for m in excluded)
            extra_args = ["-m", marker_expr]
        else:
            extra_args = []
        return raw_paths, extra_args

    # --- Hardcoded fallbacks (used when profiles.toml absent/unreadable) ---
    if profile in ("smoke-w5", "smoke"):
        raw_paths = list(SMOKE_W5_BUNDLE)
        extra_args = []
    elif profile == "default-offline":
        # Narrow path list excludes tests/integration, tests/runtime_adapter,
        # tests/server -- these 419+ files cause the 600s timeout.
        raw_paths = list(_DEFAULT_OFFLINE_PATHS)
        marker_expr = " and ".join(f"not {m}" for m in _OFFLINE_EXCLUDED_MARKERS)
        extra_args = ["-m", marker_expr]
    elif profile == "release":
        # Full regression suite -- no marker restrictions.
        raw_paths = list(WAVE_TEST_BUNDLE)
        extra_args = []
    elif profile == "nightly":
        # Full regression + e2e + perf + characterization + golden.
        # Non-existent paths are silently dropped by _filter_existing().
        raw_paths = list(_NIGHTLY_PATHS)
        extra_args = []
    elif profile == "custom":
        if not args.bundle:
            print(
                "ERROR: --profile custom requires --bundle PATH to be specified.",
                file=sys.stderr,
            )
            sys.exit(1)
        raw_paths = _load_bundle(args.bundle)
        extra_args = []
    else:
        # Should never happen given argparse choices, but be safe
        raw_paths = list(WAVE_TEST_BUNDLE)
        extra_args = []

    return raw_paths, extra_args


def _parse_pytest_json(report_file: Path, exit_code: int) -> dict:
    """Parse pytest-json-report output and return a stats dict.

    IMPORTANT: On any failure (missing file, parse error, unreadable), this
    function NEVER returns zero-stats that could be mistaken for "all passed".
    It always sets ``status="failed"`` and ``summary_available=False`` so
    downstream callers can detect the failure unambiguously.
    """
    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errors = summary.get("error", 0)
        skipped = summary.get("skipped", 0)
        collected = summary.get("collected", 0)

        # Determine status from content + exit code
        status = "failed" if exit_code != 0 or failed > 0 or errors > 0 else "passed"

        if status == "passed":
            failure_reason_str = None
        else:
            failure_reason_str = (
                f"pytest exit_code={exit_code} failed={failed} errors={errors}"
            )

        return {
            "status": status,
            "summary_available": True,
            "failure_reason": failure_reason_str,
            "collected": collected,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
        }
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        # NEVER return zero-stats: a missing/unreadable report is always a failure.
        return {
            "status": "failed",
            "summary_available": False,
            "failure_reason": f"report file missing or unreadable: {exc}",
            "collected": None,
            "passed": None,
            "failed": None,
            "errors": None,
            "skipped": None,
        }


def _run_pytest_with_triage(
    cmd: list[str],
    cwd: str,
    timeout_s: int,
    env: dict | None = None,
) -> tuple[int, str, dict | None]:
    """Run pytest, capturing output for triage on timeout.

    Returns (returncode, full_output, triage_dict_or_None).
    triage_dict is populated only when the process was killed due to timeout.
    """
    stdout_lines: list[str] = []
    stdout_q: queue.Queue[str] = queue.Queue()

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_q.put(line)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        timed_out = True

    reader_thread.join(timeout=5)

    # Drain queue
    while not stdout_q.empty():
        try:
            stdout_lines.append(stdout_q.get_nowait())
        except queue.Empty:
            break

    returncode = proc.returncode if proc.returncode is not None else -1

    # Print captured output so the caller sees it live (via the joined thread)
    output = "".join(stdout_lines)
    print(output, end="")

    # Extract last RUNNING/PASSED/FAILED line for triage
    currently_running: str | None = None
    for line in reversed(stdout_lines):
        if "RUNNING" in line or "PASSED" in line or "FAILED" in line:
            currently_running = line.strip()[:200]
            break

    triage: dict | None = None
    if timed_out:
        triage = {
            "tail": "".join(stdout_lines[-200:]),
            "currently_running_nodeid": currently_running,
            "total_output_lines": len(stdout_lines),
        }

    return returncode, output, triage


def _build_evidence_json(
    *,
    profile: str,
    cmd: list[str],
    duration: float,
    timed_out: bool,
    returncode: int,
    stdout: str,
    summary: dict | None,
    release_head: str,
) -> dict:
    """Build the evidence dict that is written to --json-report.

    When *summary* is None (timeout, crash, or no JSON report from pytest),
    all count fields are set to ``None`` -- never to ``0`` -- so callers can
    distinguish "zero failures" from "counts unavailable".
    """
    if summary is not None and summary.get("summary_available"):
        return {
            "profile": profile,
            "command": " ".join(cmd),
            "release_head": release_head,
            "duration_seconds": duration,
            "summary_available": True,
            "status": summary.get("status", "failed"),
            "failure_reason": summary.get("failure_reason"),
            "collected": summary.get("collected"),
            "passed": summary.get("passed"),
            "failed": summary.get("failed"),
            "errors": summary.get("errors"),
            "skipped": summary.get("skipped"),
            "timeout": timed_out,
        }
    # Summary unavailable -- use null counts, NOT zero
    return {
        "profile": profile,
        "command": " ".join(cmd),
        "release_head": release_head,
        "duration_seconds": duration,
        "summary_available": False,
        "status": "failed",
        "failure_reason": "timeout" if timed_out else "no_summary",
        "collected": None,
        "passed": None,
        "failed": None,
        "errors": None,
        "skipped": None,
        "timeout": timed_out,
    }


def _git_short_head() -> str:
    """Return first 8 chars of HEAD SHA, or 'unknown'."""
    sha = _git_head()
    return sha[:8] if sha != "unknown" else sha


def main() -> int:
    # Guard Windows console encoding to avoid UnicodeEncodeError on non-ASCII output
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation):
        pass

    args = _parse_args()
    profile = args.profile

    # --- Resolve paths --------------------------------------------------
    basetemp = _resolve_dir(
        args.basetemp,
        "HI_AGENT_PYTEST_TEMPROOT",
        "hi_agent_pytest_",
    )
    cache_dir = _resolve_dir(
        args.cache_dir,
        "HI_AGENT_PYTEST_CACHE_DIR",
        "hi_agent_cache_",
    )

    # --- Pre-flight check -----------------------------------------------
    if not args.no_fail_fast_env_check:
        ok = True
        for path in (basetemp, cache_dir):
            if not _preflight_check(path):
                ok = False
        if not ok:
            return 2

    # --- Resolve bundle and extra args ----------------------------------
    raw_paths, extra_pytest_args = _resolve_bundle_and_marker_args(args)

    existing_paths, missing_paths = _filter_existing(raw_paths)

    if not existing_paths:
        print("ERROR: No test paths exist. Nothing to run.", file=sys.stderr)
        return 1

    if missing_paths:
        print(f"WARN: {len(missing_paths)} path(s) not found, skipping:")
        for p in missing_paths:
            print(f"  {p}")

    # --- Build pytest command -------------------------------------------
    # Use a temp file for pytest-json-report output so we can parse stats
    with tempfile.NamedTemporaryFile(
        suffix="-pytest-report.json",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as tmp_report:
        tmp_report_path = tmp_report.name

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        f"--basetemp={basetemp}",
        f"--override-ini=cache_dir={cache_dir}",
        "--json-report",
        f"--json-report-file={tmp_report_path}",
        *existing_paths,
        *extra_pytest_args,
    ]

    print(f"profile  : {profile}")
    print(f"basetemp : {basetemp}")
    print(f"cache_dir: {cache_dir}")
    if extra_pytest_args:
        print(f"markers  : {' '.join(extra_pytest_args)}")
    print(f"command  : {' '.join(cmd)}")
    print()

    # --- Run pytest -----------------------------------------------------
    started_at = datetime.datetime.now(datetime.UTC)
    status = "error"
    failure_reason: str | None = None
    pytest_exit_code: int = -1
    triage: dict | None = None
    stats: dict = {
        "status": "error",
        "summary_available": False,
        "failure_reason": "pytest did not complete",
        "collected": None,
        "passed": None,
        "failed": None,
        "errors": None,
        "skipped": None,
    }

    pytest_exit_code, _output, triage = _run_pytest_with_triage(
        cmd, cwd=str(ROOT), timeout_s=600
    )
    finished_at = datetime.datetime.now(datetime.UTC)

    if triage is not None:
        # Process was killed due to timeout
        status = "timeout"
        failure_reason = "pytest timed out after 600 seconds"
        stats = {
            "status": "timeout",
            "summary_available": False,
            "failure_reason": failure_reason,
            "collected": None,
            "passed": None,
            "failed": None,
            "errors": None,
            "skipped": None,
        }
        print(f"\nERROR: {failure_reason}", file=sys.stderr)
    else:
        # --- Parse stats from pytest-json-report --------------------------
        stats = _parse_pytest_json(Path(tmp_report_path), pytest_exit_code)
        status = stats["status"]
        failure_reason = stats.get("failure_reason")

    duration = (finished_at - started_at).total_seconds()

    # Clean up tmp report
    with contextlib.suppress(OSError):
        Path(tmp_report_path).unlink(missing_ok=True)

    # --- Write evidence JSON --------------------------------------------
    if args.json_report:
        try:
            pytest_version = importlib.metadata.version("pytest")
        except importlib.metadata.PackageNotFoundError:
            pytest_version = "unknown"

        # provenance is "real" when pytest actually ran and produced a summary.
        # "structural" when summary is unavailable (crash/timeout) or status
        # indicates the run never completed cleanly.
        _derived_provenance = (
            "real"
            if stats.get("summary_available") and status in ("pass", "fail")
            else "structural"
        )
        evidence = {
            "schema_version": 2,
            "provenance": _derived_provenance,
            "check": "clean_env",
            "bundle_profile": profile,
            "status": status,
            "summary_available": stats.get("summary_available", False),
            "failure_reason": failure_reason,
            "pytest_exit_code": pytest_exit_code,
            "head": _git_head(),
            "python": sys.version.split()[0],
            "pytest": pytest_version,
            "basetemp": basetemp,
            "cache_dir": cache_dir,
            "command": cmd,
            "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_seconds": duration,
            "collected": stats.get("collected"),
            "passed": stats.get("passed"),
            "failed": stats.get("failed"),
            "errors": stats.get("errors"),
            "skipped": stats.get("skipped"),
            "missing_paths": missing_paths,
            "timeout_triage": triage,
        }
        evidence_path = Path(args.json_report)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        print(f"\nEvidence JSON written to: {evidence_path}")

    return pytest_exit_code if status not in ("timeout", "error") else 1


if __name__ == "__main__":
    sys.exit(main())

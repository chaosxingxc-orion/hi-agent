#!/usr/bin/env python
"""Portable clean-environment verification wrapper.

Runs the full Wave test bundle in a clean temp directory — no repo-internal
.pytest_tmp or .pytest_cache pollution.

Exit 0: all tests passed (or skipped).
Exit 1: tests failed or pytest could not be collected.
Exit 2: pre-flight permission check failed.

Usage::

    # Default: uses system tempdir (works on any machine)
    python scripts/verify_clean_env.py

    # Custom paths (for CI or restricted environments)
    python scripts/verify_clean_env.py \\
        --basetemp /tmp/hi_agent_pytest \\
        --cache-dir /tmp/hi_agent_cache \\
        --json-report docs/delivery/<sha>-clean-env.json

    # Read test paths from a file (for integration tests / sub-bundles)
    python scripts/verify_clean_env.py --bundle /tmp/my_bundle.txt

Environment variables (lower priority than CLI args):
    HI_AGENT_PYTEST_TEMPROOT   override basetemp
    HI_AGENT_PYTEST_CACHE_DIR  override cache-dir
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Wave test bundle — paths relative to repo root.
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Wave test bundle in a portable clean environment.",
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
            "embedded WAVE_TEST_BUNDLE list."
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


def _parse_pytest_json(report_file: Path) -> dict:
    """Parse pytest-json-report output and return a stats dict."""
    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        return {
            "collected": summary.get("collected", 0),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "errors": summary.get("error", 0),
            "skipped": summary.get("skipped", 0),
        }
    except (json.JSONDecodeError, OSError, KeyError):
        return {
            "collected": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        }


def main() -> int:
    args = _parse_args()

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

    # --- Resolve bundle -------------------------------------------------
    raw_paths = _load_bundle(args.bundle) if args.bundle else list(WAVE_TEST_BUNDLE)

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
    ]

    print(f"basetemp : {basetemp}")
    print(f"cache_dir: {cache_dir}")
    print(f"command  : {' '.join(cmd)}")
    print()

    # --- Run pytest -----------------------------------------------------
    started_at = datetime.datetime.now(datetime.UTC)
    result = subprocess.run(cmd, cwd=str(ROOT))
    finished_at = datetime.datetime.now(datetime.UTC)
    duration = (finished_at - started_at).total_seconds()

    # --- Parse stats from pytest-json-report ----------------------------
    stats = _parse_pytest_json(Path(tmp_report_path))

    # Clean up tmp report
    with contextlib.suppress(OSError):
        Path(tmp_report_path).unlink(missing_ok=True)

    # --- Write evidence JSON --------------------------------------------
    if args.json_report:
        try:
            pytest_version = importlib.metadata.version("pytest")
        except importlib.metadata.PackageNotFoundError:
            pytest_version = "unknown"

        evidence = {
            "schema_version": 1,
            "head": _git_head(),
            "python": sys.version.split()[0],
            "pytest": pytest_version,
            "basetemp": basetemp,
            "cache_dir": cache_dir,
            "command": cmd,
            "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_seconds": duration,
            "collected": stats["collected"],
            "passed": stats["passed"],
            "failed": stats["failed"],
            "errors": stats["errors"],
            "skipped": stats["skipped"],
            "missing_paths": missing_paths,
        }
        evidence_path = Path(args.json_report)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        print(f"\nEvidence JSON written to: {evidence_path}")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

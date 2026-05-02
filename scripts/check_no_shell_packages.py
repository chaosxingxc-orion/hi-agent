#!/usr/bin/env python3
"""W31-H8 gate: forbid bare-shell `__init__.py` packages under agent_server/ and hi_agent/.

A "shell package" is a directory whose `__init__.py` is < 200 bytes AND has
zero peer `.py` files. Empty scaffolding of this shape repeatedly leaks
into the tree (see W31 H-track audit: agent_server/{mcp,observability,
tenancy,workspace}/) and serves as a confusable namespace placeholder.

Allow-list mechanism: a shell may be tolerated if its `__init__.py`
contains a `# stub-reason: <name+wave>` annotation in the first line.
This forces a deliberate decision (and a wave-stamped expiry trail) for
every retained empty package.

Algorithm (per directive):
  Walk agent_server/** and hi_agent/**.
  For every directory containing __init__.py:
    init_size  = len(__init__.py bytes)
    peer_files = len([f for f in dir.iterdir()
                      if f.is_file() and f.suffix == '.py'
                      and f.name != '__init__.py'])
    If init_size < 200 AND peer_files == 0:
      → it's a shell. Either
        a) `__init__.py` first line carries `# stub-reason: <...>`  → allow
        b) otherwise                                                 → fail
  Subdirectories are walked too — peer count is per-leaf-directory
  (no recursion into peer count).

Exit codes:
  0 — PASS (no shells, or all shells annotated with `# stub-reason: ...`)
  1 — FAIL (one or more unannotated shells)

Usage:
  python scripts/check_no_shell_packages.py
  python scripts/check_no_shell_packages.py --json
  python scripts/check_no_shell_packages.py --root <path>   # for tests
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit

# Directories scanned by the gate.
_SCAN_ROOTS = ("agent_server", "hi_agent")

# Threshold below which __init__.py is considered "empty enough" to be a shell.
_INIT_SIZE_THRESHOLD = 200

# Annotation that allows a deliberate stub.
_STUB_MARKER = "# stub-reason:"


def _read_first_line(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def _is_shell_dir(directory: Path) -> tuple[bool, int, int, str]:
    """Return (is_shell, init_size, peer_count, first_line).

    is_shell == True iff __init__.py exists, init_size < threshold, and
    peer_files == 0.
    """
    init = directory / "__init__.py"
    if not init.is_file():
        return (False, 0, 0, "")
    try:
        init_size = init.stat().st_size
    except OSError:
        return (False, 0, 0, "")
    peer_count = 0
    try:
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix != ".py":
                continue
            if entry.name == "__init__.py":
                continue
            peer_count += 1
    except OSError:
        return (False, init_size, 0, "")
    is_shell = init_size < _INIT_SIZE_THRESHOLD and peer_count == 0
    first_line = _read_first_line(init) if is_shell else ""
    return (is_shell, init_size, peer_count, first_line)


def _scan(root: Path, scan_roots: tuple[str, ...] = _SCAN_ROOTS) -> dict:
    """Walk scan_roots under root; classify each leaf-directory.

    Returns a dict with `violations`, `allowed_shells`, `dirs_scanned`,
    `shells_total`.
    """
    violations: list[dict] = []
    allowed: list[dict] = []
    dirs_scanned = 0
    for top in scan_roots:
        top_dir = root / top
        if not top_dir.is_dir():
            continue
        # Walk every directory (including nested).
        for d in [top_dir, *(p for p in top_dir.rglob("*") if p.is_dir())]:
            # Skip any __pycache__ directory.
            if "__pycache__" in d.parts:
                continue
            init = d / "__init__.py"
            if not init.is_file():
                continue
            dirs_scanned += 1
            is_shell, init_size, peer_count, first_line = _is_shell_dir(d)
            if not is_shell:
                continue
            rel = d.relative_to(root).as_posix()
            entry = {
                "directory": rel,
                "init_size": init_size,
                "peer_py_files": peer_count,
            }
            if first_line.startswith(_STUB_MARKER):
                entry["stub_reason"] = first_line[len(_STUB_MARKER):].strip()
                allowed.append(entry)
            else:
                violations.append(entry)
    return {
        "violations": violations,
        "allowed_shells": allowed,
        "dirs_scanned": dirs_scanned,
        "shells_total": len(violations) + len(allowed),
    }


def evaluate(root: Path, scan_roots: tuple[str, ...] = _SCAN_ROOTS) -> GateResult:
    report = _scan(root, scan_roots=scan_roots)
    evidence = {
        "scan_roots": list(scan_roots),
        "init_size_threshold": _INIT_SIZE_THRESHOLD,
        "dirs_scanned": report["dirs_scanned"],
        "shells_total": report["shells_total"],
        "allowed_shells": report["allowed_shells"],
        "violations": report["violations"],
    }
    if report["violations"]:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="no_shell_packages",
            reason=(
                f"{len(report['violations'])} unannotated shell package(s) "
                f"under {'/'.join(scan_roots)}; add `# stub-reason: <name+wave>` "
                f"to first line of __init__.py or delete the directory"
            ),
            evidence=evidence,
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="no_shell_packages",
        reason=(
            f"no unannotated shell packages "
            f"({len(report['allowed_shells'])} annotated stub(s) tolerated)"
        ),
        evidence=evidence,
    )


def _print_human(result: GateResult) -> None:
    if result.status is GateStatus.PASS:
        print(f"PASS (W31-H8): {result.reason}")
        for s in result.evidence.get("allowed_shells", []):
            print(
                f"  ALLOWED  {s['directory']}  "
                f"(stub-reason: {s.get('stub_reason', '')!r})"
            )
        return
    print(f"FAIL (W31-H8): {result.reason}")
    for v in result.evidence.get("violations", []):
        print(
            f"  SHELL    {v['directory']}  "
            f"(init_size={v['init_size']}B, peer_py_files={v['peer_py_files']})"
        )
    for s in result.evidence.get("allowed_shells", []):
        print(
            f"  ALLOWED  {s['directory']}  "
            f"(stub-reason: {s.get('stub_reason', '')!r})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit single-line multistatus JSON (and exit).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repo root to scan (default: detected from script location).",
    )
    args = parser.parse_args()

    result = evaluate(args.root)

    if args.json:
        # emit() writes JSON and exits with the right code.
        emit(result)
        return 0  # unreachable; emit calls sys.exit

    _print_human(result)
    return 0 if result.status is GateStatus.PASS else 1


if __name__ == "__main__":
    sys.exit(main())

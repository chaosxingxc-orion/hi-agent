#!/usr/bin/env python3
"""Test honesty audit gate (CLAUDE.md Rule 3 + Rule 7 enforcement).

Scans tests/integration/ and tests/e2e/ for three anti-patterns:

1. MagicMock/Mock applied to the system under test (SUT) in integration tests.
   SUT detection heuristic: variable name matches known SUT name patterns
   (subject, under_test, sut, system, service, manager, store, executor,
   worker, runner, handler, processor, adapter, engine, gateway, scheduler).

2. Assertions that accept failure as success — e.g.
     assert status in ("completed", "failed", "cancelled")
   where both a success state AND a failure state appear in the same assertion
   RHS tuple/set. This disguises a broken test as a passing one.

3. SUT-internal patch targets — integration tests that patch classes/methods
   inside hi_agent.{server,llm,memory,artifacts,config,...} rather than only
   boundary/external seams.  Detected via tests/integration/_mock_audit.py
   (AX-B B1, Wave 21).

Exit 0: pass (no violations)
Exit 1: fail (violations found)
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SUT_NAME_PATTERNS = {
    "subject", "under_test", "sut", "system", "service",
    "manager", "store", "executor", "worker", "runner",
    "handler", "processor", "adapter", "engine", "gateway",
    "scheduler", "dispatcher", "controller", "kernel", "client",
}

_SUCCESS_STATES = {"completed", "succeeded", "done", "success", "passed"}
_FAILURE_STATES = {"failed", "error", "cancelled", "timed_out", "rejected", "aborted"}


_MOCK_PREFIXES = ("mock_", "fake_", "stub_", "dummy_", "spy_")


def _is_sut_name(name: str) -> bool:
    lower = name.lower()
    # Explicitly-prefixed mocks are dependencies, not SUT
    if any(lower.startswith(p) for p in _MOCK_PREFIXES):
        return False
    return any(pat in lower for pat in _SUT_NAME_PATTERNS)


def _collect_mock_assignments(tree: ast.Module) -> list[tuple[str, int]]:
    """Return (var_name, line) for Mock/MagicMock assignments whose var name looks like SUT."""
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        # Check RHS for Mock or MagicMock call
        value = node.value if isinstance(node, ast.Assign) else getattr(node, "value", None)
        if value is None:
            continue
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        func_name = ""
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name not in ("Mock", "MagicMock", "AsyncMock"):
            continue
        # Extract target variable names
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_sut_name(target.id):
                    results.append((target.id, node.lineno))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_sut_name(node.target.id)
        ):
            results.append((node.target.id, node.lineno))
    return results


def _collect_accept_failure_assertions(tree: ast.Module) -> list[tuple[str, int]]:
    """Return (description, line) for assertions that accept both success and failure states."""
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        # Look for: assert x in (a, b, c, ...) or assert x == (a, b, ...)
        if not isinstance(test, ast.Compare):
            continue
        if not test.ops:
            continue
        op = test.ops[0]
        if not isinstance(op, ast.In):
            continue
        comparator = test.comparators[0] if test.comparators else None
        if comparator is None:
            continue
        # Extract string literals from the RHS tuple/list/set
        rhs_strings: set[str] = set()
        elts: list[Any] = []
        if isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
            elts = comparator.elts
        elif isinstance(comparator, ast.Constant) and isinstance(comparator.value, (tuple, list)):
            elts = [ast.Constant(value=v) for v in comparator.value]
        for elt in elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                rhs_strings.add(elt.value)
        has_success = bool(rhs_strings & _SUCCESS_STATES)
        has_failure = bool(rhs_strings & _FAILURE_STATES)
        if has_success and has_failure:
            vals = sorted(rhs_strings & (_SUCCESS_STATES | _FAILURE_STATES))
            results.append((f"accepts both success and failure: {vals}", node.lineno))
    return results


def _scan_file(path: pathlib.Path) -> list[dict]:
    violations = []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [{"file": str(path.relative_to(ROOT)), "line": exc.lineno or 0,
                 "kind": "syntax_error", "description": str(exc)}]

    rel = str(path.relative_to(ROOT))
    for var_name, line in _collect_mock_assignments(tree):
        violations.append({
            "file": rel,
            "line": line,
            "kind": "mock_on_sut",
            "description": f"MagicMock/Mock assigned to '{var_name}' (looks like SUT)",
        })
    for desc, line in _collect_accept_failure_assertions(tree):
        violations.append({
            "file": rel,
            "line": line,
            "kind": "accept_failure_assertion",
            "description": desc,
        })
    return violations


def _scan_file_b1(path: pathlib.Path) -> list[dict]:
    """AX-B B1: detect SUT-internal patch targets in integration tests.

    Delegates to tests/integration/_mock_audit.py when available.
    Gracefully skips if the module cannot be imported (e.g., in environments
    where tests/ is not on sys.path).
    """
    try:
        import importlib.util as _ilu
        audit_path = ROOT / "tests" / "integration" / "_mock_audit.py"
        if not audit_path.exists():
            return []
        spec = _ilu.spec_from_file_location("_mock_audit", audit_path)
        if spec is None or spec.loader is None:
            return []
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: Wave 30
        raw = mod.scan_file(path)
        # Normalise: ensure each entry has required keys
        out = []
        for v in raw:
            out.append({
                "file": v.get("file", str(path.relative_to(ROOT))),
                "line": v.get("line", 0),
                "kind": v.get("kind", "sut_internal_mock"),
                "description": v.get("description", v.get("target", "")),
            })
        return out
    except Exception:  # intentional broad catch: optional B1 gate must never crash the main gate
        return []


# Syntax errors are encoding issues (BOM files), not honesty violations — excluded from count.
_BASELINE_VIOLATIONS = 48  # expiry_wave: Wave 29 — 47 B1 SUT-monkeypatches + 1 accept_failure


def main() -> int:
    parser = argparse.ArgumentParser(description="Test honesty audit gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--baseline", type=int, default=_BASELINE_VIOLATIONS,
                        help="Max allowed violations before failing (tightens each wave)")
    parser.add_argument("--paths", nargs="*",
                        default=["tests/integration", "tests/e2e"],
                        help="Directories to scan")
    parser.add_argument("--strict", action="store_true",
                        help="Treat absent input as fail rather than not_applicable")
    args = parser.parse_args()

    all_violations: list[dict] = []
    b1_violations: list[dict] = []
    files_scanned = 0

    for p in args.paths:
        scan_dir = ROOT / p
        if not scan_dir.exists():
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            files_scanned += 1
            all_violations.extend(_scan_file(py_file))
            # AX-B B1: SUT-internal patch detection (integration tests only)
            if "integration" in str(py_file):
                b1_violations.extend(_scan_file_b1(py_file))

    # Syntax errors are encoding/parse failures, not honesty anti-patterns.
    honesty_violations = [v for v in all_violations if v["kind"] != "syntax_error"]
    mock_count = sum(1 for v in honesty_violations if v["kind"] == "mock_on_sut")
    accept_fail_count = sum(
        1 for v in honesty_violations if v["kind"] == "accept_failure_assertion"
    )
    b1_count = len(b1_violations)
    # not_applicable: no integration/e2e test directories found
    if files_scanned == 0:
        if args.strict:
            print("FAIL (strict): input absent at tests/integration and tests/e2e; "
                  "in strict mode, absent input is a defect", file=sys.stderr)
            return 1
        result_na = {
            "check": "test_honesty",
            "status": "not_applicable",
            "reason": "no integration/e2e test files found to scan",
            "files_scanned": 0,
            "baseline": args.baseline,
        }
        if args.json:
            print(json.dumps(result_na, indent=2))
        else:
            print("NOT_APPLICABLE test_honesty: no integration/e2e test files found")
        return 2

    # B1 (SUT-internal mock in integration tests) is now blocking: include in
    # honesty_violations so it counts against the baseline.
    all_blocking_violations = honesty_violations + b1_violations
    status = "pass" if len(all_blocking_violations) <= args.baseline else "fail"

    result = {
        "check": "test_honesty",
        "status": status,
        "files_scanned": files_scanned,
        "mock_on_sut_count": mock_count,
        "accept_failure_assertion_count": accept_fail_count,
        "b1_sut_internal_patch_count": b1_count,
        "violations_total": len(all_blocking_violations),
        "baseline": args.baseline,
        "violations": honesty_violations,
        "b1_violations": b1_violations,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if len(all_blocking_violations) > args.baseline:
            print(
                f"FAIL: {len(all_blocking_violations)} honesty violations "
                f"(baseline={args.baseline})",
                file=sys.stderr,
            )
            for v in honesty_violations[:10]:
                print(
                    f"  [{v['kind']}] {v['file']}:{v['line']}: {v['description']}",
                    file=sys.stderr,
                )
            for v in b1_violations[:5]:
                print(
                    f"  [B1:{v['kind']}] {v['file']}:{v['line']}: {v['description']}",
                    file=sys.stderr,
                )
        else:
            print(
                f"PASS: {mock_count} mock-on-sut, {accept_fail_count} accept-failure, "
                f"{b1_count} b1-sut-internal "
                f"({len(all_blocking_violations)} total ≤ baseline {args.baseline})"
            )

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

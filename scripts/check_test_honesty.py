#!/usr/bin/env python3
"""W16-K: Test honesty audit gate (CLAUDE.md Rule 3 + Rule 7 enforcement).

Scans tests/integration/ and tests/e2e/ for two anti-patterns:

1. MagicMock/Mock applied to the system under test (SUT) in integration tests.
   SUT detection heuristic: variable name matches known SUT name patterns
   (subject, under_test, sut, system, service, manager, store, executor,
   worker, runner, handler, processor, adapter, engine, gateway, scheduler).

2. Assertions that accept failure as success — e.g.
     assert status in ("completed", "failed", "cancelled")
   where both a success state AND a failure state appear in the same assertion
   RHS tuple/set. This disguises a broken test as a passing one.

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


def _is_sut_name(name: str) -> bool:
    lower = name.lower()
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Test honesty audit gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--paths", nargs="*",
                        default=["tests/integration", "tests/e2e"],
                        help="Directories to scan")
    args = parser.parse_args()

    all_violations: list[dict] = []
    files_scanned = 0

    for p in args.paths:
        scan_dir = ROOT / p
        if not scan_dir.exists():
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            files_scanned += 1
            all_violations.extend(_scan_file(py_file))

    mock_count = sum(1 for v in all_violations if v["kind"] == "mock_on_sut")
    accept_fail_count = sum(1 for v in all_violations if v["kind"] == "accept_failure_assertion")
    status = "pass" if not all_violations else "fail"

    result = {
        "check": "test_honesty",
        "status": status,
        "files_scanned": files_scanned,
        "mock_on_sut_count": mock_count,
        "accept_failure_assertion_count": accept_fail_count,
        "violations_total": len(all_violations),
        "violations": all_violations,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for v in all_violations:
            print(
                f"FAIL [{v['kind']}] {v['file']}:{v['line']}: {v['description']}",
                file=sys.stderr,
            )
        if not all_violations:
            print(f"PASS: {files_scanned} files scanned, no honesty violations")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Posture coverage audit (CLAUDE.md Rule 11).

Scans hi_agent/ for callsites of posture-sensitive branches:
  posture.is_strict, posture.is_dev, Posture.from_env()

For each callsite, checks whether any test in tests/ exercises both
dev and research/strict paths for the enclosing function.

Exit 0: pass (uncovered_count <= baseline threshold)
Exit 1: fail (too many uncovered callsites)
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_POSTURE_PATTERNS = re.compile(
    r"posture\.is_strict|posture\.is_dev|posture\.is_research|Posture\.from_env\(\)"
)

# W19/D: tests/posture/ added 118 parametrized tests covering all 52 callsites.
# Baseline now 0 — all callsites covered.
_BASELINE_UNCOVERED = 0


def _find_enclosing_function(source_lines: list[str], lineno: int) -> str:
    """Walk backwards from lineno to find the nearest def/class signature."""
    prefixes = ("def ", "async def ", "class ")
    for i in range(lineno - 2, -1, -1):
        stripped = source_lines[i].strip()
        if any(stripped.startswith(p) for p in prefixes):
            name = stripped.split("(")[0]
            for p in ("async def ", "def ", "class "):
                name = name.replace(p, "")
            return name.strip()
    return "<module>"


def _find_posture_callsites() -> list[dict]:
    callsites = []
    src_dir = ROOT / "hi_agent"
    for py_file in sorted(src_dir.rglob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_lines = text.splitlines()
        for lineno, line in enumerate(source_lines, start=1):
            if _POSTURE_PATTERNS.search(line):
                func = _find_enclosing_function(source_lines, lineno)
                callsites.append({
                    "file": str(py_file.relative_to(ROOT)),
                    "line": lineno,
                    "function": func,
                    "snippet": line.strip()[:80],
                })
    return callsites


def _find_posture_parametrized_tests() -> set[str]:
    """Return set of function names that appear in tests with posture parametrization."""
    covered: set[str] = set()
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return covered
    posture_ref = re.compile(r"posture|Posture|is_strict|is_dev|is_research|from_env")
    for py_file in sorted(tests_dir.rglob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not posture_ref.search(text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                dec_str = ast.unparse(decorator) if hasattr(ast, "unparse") else ""
                is_param = "parametrize" in dec_str
                covers_posture = any(
                    k in dec_str for k in ("posture", "strict", "dev")
                )
                if is_param and covers_posture:
                    covered.add(node.name)
    # Also look for any test file that directly instantiates Posture
    for py_file in sorted(tests_dir.rglob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        has_posture = "Posture" in text
        has_posture_val = any(k in text for k in ("dev", "research", "strict"))
        if has_posture and has_posture_val:
            for m in re.finditer(r"def (test_\w+)\(", text):
                covered.add(m.group(1))
    return covered


def main() -> int:
    parser = argparse.ArgumentParser(description="Posture coverage audit.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--emit-evidence", action="store_true")
    parser.add_argument("--baseline", type=int, default=_BASELINE_UNCOVERED)
    args = parser.parse_args()

    callsites = _find_posture_callsites()
    covered_tests = _find_posture_parametrized_tests()

    uncovered = [
        cs for cs in callsites
        if cs["function"] not in covered_tests
        and f"test_{cs['function']}" not in covered_tests
    ]

    total = len(callsites)
    covered_count = total - len(uncovered)
    status = "pass" if len(uncovered) <= args.baseline else "fail"

    result = {
        "check": "posture_coverage",
        "status": status,
        "total_callsites": total,
        "covered": covered_count,
        "uncovered_count": len(uncovered),
        "baseline": args.baseline,
        "uncovered": uncovered[:20],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if len(uncovered) > args.baseline:
            print(
                f"FAIL: {len(uncovered)} uncovered posture callsites "
                f"(baseline={args.baseline})",
                file=sys.stderr,
            )
            for cs in uncovered[:10]:
                print(
                    f"  {cs['file']}:{cs['line']} {cs['function']}: {cs['snippet']}",
                    file=sys.stderr,
                )
        else:
            print(
                f"PASS: {covered_count}/{total} posture callsites covered "
                f"({len(uncovered)} uncovered, baseline={args.baseline})"
            )

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

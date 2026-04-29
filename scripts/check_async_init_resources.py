#!/usr/bin/env python3
"""CL4 gate: detect httpx.AsyncClient / aiohttp.ClientSession constructed in __init__.

Rule 5 forbids creating async resources in __init__ of a sync-facing class.
Every match must be lazy-initialized (set to None in __init__; create on first
async call) or per-call constructed inside `async with`.

Exit 0: no violations.
Exit 1: violations found.
"""
from __future__ import annotations

import ast
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_FORBIDDEN_TYPES = {
    "AsyncClient",     # httpx.AsyncClient
    "ClientSession",   # aiohttp.ClientSession
}

# Files with annotated exceptions (e.g. truly per-call construction).
_EXEMPT_COMMENT = "rule5-exempt"


def _has_exempt_comment(source_lines: list[str], lineno: int) -> bool:
    line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
    return _EXEMPT_COMMENT in line


def _check_file(path: pathlib.Path) -> list[dict]:
    """Return list of violation dicts for the given file."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    violations: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name != "__init__":
                continue
            for stmt in ast.walk(item):
                if not isinstance(stmt, ast.Call):
                    continue
                func = stmt.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in _FORBIDDEN_TYPES:
                    lineno = stmt.lineno
                    if _has_exempt_comment(source_lines, lineno):
                        continue
                    violations.append({
                        "file": str(path.relative_to(ROOT)),
                        "class": node.name,
                        "line": lineno,
                        "type": name,
                        "snippet": source_lines[lineno - 1].strip(),
                    })
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for async resources in __init__.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    scan_dirs = [
        ROOT / "hi_agent",
        ROOT / "agent_kernel",
    ]
    all_violations: list[dict] = []
    for d in scan_dirs:
        for py_file in sorted(d.rglob("*.py")):
            all_violations.extend(_check_file(py_file))

    if args.json:
        print(json.dumps({"violations": all_violations, "count": len(all_violations)}, indent=2))
    else:
        if all_violations:
            print(f"FAIL: {len(all_violations)} async-resource-in-__init__ violation(s):", file=sys.stderr)
            for v in all_violations:
                print(f"  {v['file']}:{v['line']} [{v['class']}.__init__] {v['type']}(..)", file=sys.stderr)
        else:
            print("PASS: no async resources constructed in __init__")

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())

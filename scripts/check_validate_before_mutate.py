#!/usr/bin/env python3
"""CI gate: in route handlers, validators must precede mutators.

AST-scans routes_*.py for async handle_* functions. Each function
must call a known validator before any known mutator.

Known validators: validate_run_request_or_raise, require_tenant_context,
                  validate_resource_ownership, get_or_404_owned
Known mutators: reserve_or_replay, upsert, enqueue, register, submit,
               ingest_, apply_decision, optimize_prompt
"""
from __future__ import annotations

import argparse
import ast
import sys
import pathlib
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _governance_json import emit_result

ROOT = Path(__file__).parent.parent

VALIDATORS = frozenset({
    "validate_run_request_or_raise",
    "validate_resource_ownership",
    "get_or_404_owned",
    "require_tenant_context",
})

MUTATORS = frozenset({
    "reserve_or_replay",
    "upsert",
    "enqueue",
    "register",
    "submit",
    "apply_decision",
    "optimize_prompt",
})


def get_call_names(func_node: ast.FunctionDef) -> list[str]:
    """Return list of function call names in source order (by line then col)."""
    calls: list[tuple[int, int, str]] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            line = getattr(node, "lineno", 0)
            col = getattr(node, "col_offset", 0)
            if isinstance(node.func, ast.Name):
                calls.append((line, col, node.func.id))
            elif isinstance(node.func, ast.Attribute):
                calls.append((line, col, node.func.attr))
    calls.sort()
    return [name for _, _, name in calls]


def check_file(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    errors = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not node.name.startswith("handle_"):
            continue
        call_names = get_call_names(node)
        first_validator = next((i for i, n in enumerate(call_names) if n in VALIDATORS), None)
        first_mutator = next((i for i, n in enumerate(call_names) if n in MUTATORS), None)
        if first_mutator is not None and first_validator is None:
            errors.append(
                f"  {path.relative_to(ROOT)}::{node.name}: "
                f"mutator '{call_names[first_mutator]}' called but no validator found"
            )
        elif (
            first_mutator is not None
            and first_validator is not None
            and first_mutator < first_validator
        ):
            errors.append(
                f"  {path.relative_to(ROOT)}::{node.name}: "
                f"mutator '{call_names[first_mutator]}' (pos {first_mutator}) "
                f"precedes validator '{call_names[first_validator]}' (pos {first_validator})"
            )
    return errors


def _parse_validate_error(text: str) -> dict:
    """Parse an error string into a structured dict."""
    import re
    # Format: "  file::func_name: message"
    m = re.match(r"\s+([^:]+)::(\w+): (.*)", text)
    if m:
        return {"file": m.group(1), "function": m.group(2), "text": m.group(3)}
    return {"text": text.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check validate-before-mutate ordering")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    args = parser.parse_args()

    route_files = list(ROOT.glob("hi_agent/server/routes_*.py"))
    errors = []
    for path in route_files:
        errors.extend(check_file(path))

    if args.json:
        structured = [_parse_validate_error(e) for e in errors]
        emit_result(
            "validate_before_mutate",
            "pass" if not errors else "fail",
            violations=structured,
            counts={"sites_checked": len(route_files)},
        )

    if errors:
        print("FAIL check_validate_before_mutate:")
        for e in errors:
            print(e)
        return 1
    print("OK check_validate_before_mutate")
    return 0


if __name__ == "__main__":
    sys.exit(main())

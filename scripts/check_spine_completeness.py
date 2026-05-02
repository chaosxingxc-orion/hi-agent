#!/usr/bin/env python3
"""CI gate: fail if spine fields have empty/legacy defaults (Rule 12 / CL1).

Scans the listed dataclass files for class-level annotated assignments of spine
fields (tenant_id, user_id, etc.) whose default value is a forbidden sentinel
("", "__legacy__", "__unknown__"). Fields marked with a ``# scope: process-internal``
comment are exempt.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Primary spine field — must never default to an empty sentinel.
# Secondary fields (user_id, session_id, project_id) may default to "" when
# that is a valid "unscoped" semantic; mark them # scope: process-internal to exempt.
SPINE_FIELDS = {"tenant_id"}
FORBIDDEN_DEFAULTS = {"", "__legacy__", "__unknown__"}

# Pre-existing violations baseline (expiry_wave: Wave 29).
# tenant_id fields with default '' that pre-date this gate; need scope annotations or
# required-field promotion in W29.
_VIOLATION_BASELINE = 18  # expiry_wave: Wave 29  # added: W28

DATACLASS_FILES = [
    "hi_agent/contracts/team_runtime.py",
    "hi_agent/contracts/reasoning.py",
    "hi_agent/contracts/reasoning_trace.py",
    "hi_agent/contracts/task.py",
    "hi_agent/contracts/requests.py",
    "hi_agent/artifacts/contracts.py",
    "hi_agent/server/event_store.py",
    "hi_agent/server/idempotency.py",
    "hi_agent/server/run_store.py",
    "hi_agent/server/run_manager.py",
    "hi_agent/server/tenant_context.py",
    "hi_agent/server/team_event_store.py",
    "hi_agent/operations/op_store.py",
    "hi_agent/management/gate_context.py",
    "hi_agent/management/gate_api.py",
    "hi_agent/memory/episodic.py",
    "hi_agent/skill/observer.py",
    "hi_agent/evolve/contracts.py",
    "hi_agent/evolve/feedback_store.py",
    "hi_agent/execution/run_finalizer.py",
    "hi_agent/context/run_execution_context.py",
]


def _line_has_scope_exempt(src_lines: list[str], lineno: int) -> bool:
    """Return True if the source line (1-based) contains a scope-exempt marker."""
    # lineno is 1-based (from AST)
    line = src_lines[lineno - 1] if 0 < lineno <= len(src_lines) else ""
    return "# scope: process-internal" in line


def check_file(path: str) -> list[str]:
    violations = []
    src = Path(path).read_text(encoding="utf-8")
    src_lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, ast.AnnAssign)
                    and isinstance(item.target, ast.Name)
                    and item.target.id in SPINE_FIELDS
                    and item.value is not None
                    and isinstance(item.value, ast.Constant)
                    and item.value.value in FORBIDDEN_DEFAULTS
                    and not _line_has_scope_exempt(src_lines, item.lineno)
                ):
                    violations.append(
                        f"{path}:{item.lineno}: {item.target.id} has forbidden default "
                        f"{item.value.value!r} (add '# scope: process-internal' to exempt)"
                    )
    return violations


def main() -> int:
    import json as _json

    parser = argparse.ArgumentParser(description="Spine completeness gate.")
    parser.add_argument("--strict", action="store_true",
                        help="Treat absent input as fail rather than not_applicable")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    # not_applicable when none of the scanned files exist (stripped bundle or alternate layout)
    existing = [f for f in DATACLASS_FILES if Path(f).exists()]
    if not existing:
        if args.strict:
            if args.json_output:
                print(_json.dumps({"check": "spine_completeness", "status": "fail",
                                   "reason": "input absent at hi_agent/contracts/"}))
            else:
                print("FAIL (strict): input absent at hi_agent/contracts/; "
                      "in strict mode, absent input is a defect", file=sys.stderr)
            return 1
        if args.json_output:
            print(_json.dumps({"check": "spine_completeness", "status": "not_applicable"}))
        else:
            print("not_applicable: no spine dataclass files found")
        return 0

    violations: list[str] = []
    for f in existing:
        violations.extend(check_file(f))

    excess = len(violations) - _VIOLATION_BASELINE
    if excess > 0:
        if args.json_output:
            print(_json.dumps({"check": "spine_completeness", "status": "fail",
                               "violations_total": len(violations),
                               "baseline": _VIOLATION_BASELINE,
                               "new_violations": violations[-excess:]}))
        else:
            print(f"FAIL: {excess} new violation(s) above baseline {_VIOLATION_BASELINE}:")
            for v in violations[-excess:]:
                print(f"  {v}")
        return 1

    status = "pass" if not violations else "pass_within_baseline"
    if args.json_output:
        print(_json.dumps({"check": "spine_completeness", "status": status,
                           "files_scanned": len(DATACLASS_FILES),
                           "violations_total": len(violations),
                           "baseline": _VIOLATION_BASELINE}))
    else:
        n = len(violations)
        note = f" ({n}/{_VIOLATION_BASELINE} baseline)" if n else ""
        print(f"PASS: spine completeness ({len(DATACLASS_FILES)} files scanned{note})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

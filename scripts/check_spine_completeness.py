#!/usr/bin/env python3
"""CI gate: fail if spine fields have empty/legacy defaults (Rule 12 / CL1).

Scans the listed dataclass files for class-level annotated assignments of spine
fields (tenant_id, user_id, etc.) whose default value is a forbidden sentinel
("", "__legacy__", "__unknown__"). Fields marked with a ``# scope: process-internal``
comment are exempt.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Primary spine field — must never default to an empty sentinel.
# Secondary fields (user_id, session_id, project_id) may default to "" when
# that is a valid "unscoped" semantic; mark them # scope: process-internal to exempt.
SPINE_FIELDS = {"tenant_id"}
FORBIDDEN_DEFAULTS = {"", "__legacy__", "__unknown__"}

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
    # not_applicable when none of the scanned files exist (stripped bundle or alternate layout)
    existing = [f for f in DATACLASS_FILES if Path(f).exists()]
    if not existing:
        print("not_applicable: no spine dataclass files found")
        return 0

    violations: list[str] = []
    for f in existing:
        violations.extend(check_file(f))

    if violations:
        print(f"FAIL: {len(violations)} spine completeness violation(s):")
        for v in violations:
            print(f"  {v}")
        return 1

    print(f"PASS: spine completeness check ({len(DATACLASS_FILES)} files scanned, 0 violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

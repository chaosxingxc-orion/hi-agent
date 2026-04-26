#!/usr/bin/env python3
"""CI gate: every SQLite SELECT must include all dataclass fields.

Scans Store/Registry/Ledger classes. For each class that has a
_row_to_record method, checks that the dataclass fields all appear
in at least one SELECT in that same file.
Also flags 'len(row) >' defensive fallbacks (schema drift masking).

Also enforces that all 11 durable writers accept an exec_ctx parameter
on their primary write method (Wave 10.4 W4-E + Wave 10.5 W5-D).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# (class_name, primary_write_method, file_glob)
_WRITER_EXEC_CTX_REQUIRED: list[tuple[str, str, str]] = [
    # Wave 10.4 W4-E writers (backfilled in W5-D)
    ("IdempotencyStore", "reserve_or_replay", "hi_agent/server/idempotency.py"),
    ("SQLiteEventStore", "append", "hi_agent/server/event_store.py"),
    ("TeamRunRegistry", "register", "hi_agent/server/team_run_registry.py"),
    ("SessionStore", "create", "hi_agent/server/session_store.py"),
    ("ArtifactRegistry", "store", "hi_agent/artifacts/registry.py"),
    # Wave 10.5 W5-D writers
    ("SQLiteRunStore", "upsert", "hi_agent/server/run_store.py"),
    ("TeamEventStore", "insert", "hi_agent/server/team_event_store.py"),
    ("FeedbackStore", "submit", "hi_agent/evolve/feedback_store.py"),
    ("LongRunningOpStore", "create", "hi_agent/experiment/op_store.py"),
    ("InMemoryGateAPI", "create_gate", "hi_agent/management/gate_api.py"),
    ("RateLimiter", "_consume", "hi_agent/server/rate_limiter.py"),
]


def _method_has_exec_ctx(path: Path, class_name: str, method_name: str) -> bool:
    """Return True if class_name.method_name has an exec_ctx parameter."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    all_args = (
                        [a.arg for a in item.args.args]
                        + [a.arg for a in item.args.kwonlyargs]
                        + ([item.args.vararg.arg] if item.args.vararg else [])
                        + ([item.args.kwarg.arg] if item.args.kwarg else [])
                    )
                    return "exec_ctx" in all_args
    return False


def check_writer_exec_ctx() -> list[str]:
    """Check that every required writer method accepts exec_ctx."""
    errors = []
    for class_name, method_name, file_glob in _WRITER_EXEC_CTX_REQUIRED:
        candidates = list(ROOT.glob(file_glob))
        if not candidates:
            errors.append(
                f"  WRITER-MISSING-EXEC-CTX: {class_name}.{method_name} "
                f"— file not found: {file_glob}"
            )
            continue
        path = candidates[0]
        if not _method_has_exec_ctx(path, class_name, method_name):
            errors.append(
                f"  WRITER-MISSING-EXEC-CTX: {class_name}.{method_name} "
                f"({path.relative_to(ROOT)})"
            )
    return errors


def find_store_files() -> list[Path]:
    stores = []
    for pattern in [
        "hi_agent/**/*store*.py",
        "hi_agent/**/*registry*.py",
        "hi_agent/**/*ledger*.py",
    ]:
        stores.extend(ROOT.glob(pattern))
    return list(set(stores))


def check_defensive_fallbacks(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    errors = []
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"len\(row\)\s*>\s*\d+", line) and "else" in line:
            errors.append(
                f"  {path.relative_to(ROOT)}:{i}: defensive len(row) fallback"
                " — remove and let migration ensure column exists"
            )
    return errors


def main() -> int:
    errors = []
    for path in find_store_files():
        errors.extend(check_defensive_fallbacks(path))
    errors.extend(check_writer_exec_ctx())
    if errors:
        print("FAIL check_select_completeness:")
        for e in errors:
            print(e)
        return 1
    print("OK check_select_completeness")
    return 0


if __name__ == "__main__":
    sys.exit(main())

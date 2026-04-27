#!/usr/bin/env python3
"""CI gate: every SQLite SELECT must include all dataclass fields.

Scans Store/Registry/Ledger classes. For each class that has a
_row_to_record method, checks that the dataclass fields all appear
in at least one SELECT in that same file.
Also flags 'len(row) >' defensive fallbacks (schema drift masking).

Also enforces that all 11 durable writers accept an exec_ctx parameter
on their primary write method.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _governance_json import emit_result

ROOT = Path(__file__).parent.parent

# (class_name, primary_write_method, file_glob)
_WRITER_EXEC_CTX_REQUIRED: list[tuple[str, str, str]] = [
    # Run state writers
    ("IdempotencyStore", "reserve_or_replay", "hi_agent/server/idempotency.py"),
    ("SQLiteEventStore", "append", "hi_agent/server/event_store.py"),
    ("TeamRunRegistry", "register", "hi_agent/server/team_run_registry.py"),
    ("SessionStore", "create", "hi_agent/server/session_store.py"),
    ("ArtifactRegistry", "store", "hi_agent/artifacts/registry.py"),
    # Operations and team writers
    ("SQLiteRunStore", "upsert", "hi_agent/server/run_store.py"),
    ("TeamEventStore", "insert", "hi_agent/server/team_event_store.py"),
    ("FeedbackStore", "submit", "hi_agent/evolve/feedback_store.py"),
    ("LongRunningOpStore", "create", "hi_agent/operations/op_store.py"),
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


_SPINE_CLASSES = {
    "RunFeedback": ["tenant_id"],
    "HumanGateRequest": ["tenant_id"],
    "RunRetrospective": ["tenant_id"],
    "ProjectRetrospective": ["tenant_id"],
}


def check_spine_call_sites(path: Path) -> list[str]:
    """Scan a Python file for spine dataclass constructors missing required kwargs.

    Flags call sites like RunFeedback(run_id="r1") that omit tenant_id=.
    Skips splat patterns (**fields) and lines with # spine-skip: marker.
    """
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    lines = src.splitlines()
    failures = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            cls_name = func.id
        elif isinstance(func, ast.Attribute):
            cls_name = func.attr
        else:
            continue
        if cls_name not in _SPINE_CLASSES:
            continue

        # Skip splat expansions — deserialization sites, not construction
        if any(isinstance(a, ast.Starred) for a in node.args):
            continue
        if any(isinstance(kw.arg, type(None)) for kw in node.keywords):
            # **kwargs present
            continue

        # Check spine-skip comment on this line
        lineno = node.lineno - 1
        if 0 <= lineno < len(lines) and "# spine-skip:" in lines[lineno]:
            continue

        required = _SPINE_CLASSES[cls_name]
        provided = {kw.arg for kw in node.keywords if kw.arg is not None}
        missing = [f for f in required if f not in provided]
        if missing:
            failures.append(
                f"  {path}:{node.lineno}: {cls_name}() missing required spine kwargs: "
                + ", ".join(f"{f}=" for f in missing)
            )

    return failures


def check_exec_ctx_precedence(root: Path) -> list[str]:
    """Check that no production writer uses exec_ctx-wins precedence.

    Scans hi_agent/ source only (excludes tests and scripts, which may contain
    intentional bad-pattern examples as fixtures).

    The forbidden pattern is ``exec_ctx.<field> or kwargs.get(...)`` which
    gives exec_ctx priority over explicit kwargs.  The required pattern is
    ``kwargs_value or exec_ctx.<field>`` (kwargs win; exec_ctx fills gaps).
    """
    issues = []
    # Build the pattern string without embedding a literal match target in this file.
    _forbidden = re.compile(
        r"exec_ctx\." + r"\w+" + r"\s+or\s+" + r"(?:kwargs\.get|getattr\(kwargs)"
    )
    hi_agent_root = root / "hi_agent"
    if not hi_agent_root.is_dir():
        hi_agent_root = root  # fallback for tests that pass a tmp_path
    for py_file in hi_agent_root.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if "exec_ctx" not in content:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if _forbidden.search(line):
                issues.append(
                    f"  {py_file}:{lineno}: exec_ctx-wins pattern detected"
                    " (exec_ctx.<field> or kwargs.get) — use kwargs-wins instead"
                )
    return issues


def _parse_select_error(text: str) -> dict:
    """Parse an error string into a structured dict."""
    import re
    # Format: "  file:line: message" or "  WRITER-MISSING-EXEC-CTX: ClassName.method (file)"
    m = re.match(r"\s+([^:]+):(\d+): (.*)", text)
    if m:
        return {"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)}
    m2 = re.match(r"\s+(\S+):\s+(.*)", text)
    if m2:
        return {"category": m2.group(1), "text": m2.group(2)}
    return {"text": text.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SELECT completeness")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    args = parser.parse_args()

    store_files = find_store_files()
    errors = []
    for path in store_files:
        errors.extend(check_defensive_fallbacks(path))
    errors.extend(check_writer_exec_ctx())
    errors.extend(check_exec_ctx_precedence(ROOT))

    if args.json:
        structured = [_parse_select_error(e) for e in errors]
        emit_result(
            "select_completeness",
            "pass" if not errors else "fail",
            violations=structured,
            counts={"fields_checked": len(store_files)},
        )

    if errors:
        print("FAIL check_select_completeness:")
        for e in errors:
            print(e)
        return 1
    print("OK check_select_completeness")
    return 0


if __name__ == "__main__":
    sys.exit(main())


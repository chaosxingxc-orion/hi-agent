#!/usr/bin/env python3
"""CI gate: every dataclass on the contract spine must declare tenant_id (Rule 12).

Walks AST of dataclass-decorated classes under:
  - hi_agent/contracts/
  - hi_agent/artifacts/
  - agent_server/contracts/
  - hi_agent/server/{run_store,idempotency,team_run_registry,event_store}.py

For each @dataclass-decorated class, checks for a tenant_id field declaration.
A class may be exempted with a `# scope: process-internal` comment on the line
immediately above (or as a leading comment in) the class declaration.

Exits 0 on PASS, 1 on FAIL. Emits multistatus JSON when --json is passed and
scripts/_governance/multistatus.py is importable.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories to walk recursively for dataclass declarations.
SCAN_DIRS = [
    "hi_agent/contracts",
    "hi_agent/artifacts",
    "agent_server/contracts",
]

# Specific files to scan in addition to the directories above.
SCAN_FILES = [
    "hi_agent/server/run_store.py",
    "hi_agent/server/idempotency.py",
    "hi_agent/server/team_run_registry.py",
    "hi_agent/server/event_store.py",
]

REQUIRED_FIELD = "tenant_id"
EXEMPT_MARKER = "# scope: process-internal"


def _is_dataclass_decorator(dec: ast.expr) -> bool:
    """Return True when the AST node references @dataclass."""
    if isinstance(dec, ast.Name) and dec.id == "dataclass":
        return True
    if isinstance(dec, ast.Call):
        func = dec.func
        if isinstance(func, ast.Name) and func.id == "dataclass":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "dataclass":
            return True
    return isinstance(dec, ast.Attribute) and dec.attr == "dataclass"


def _class_is_exempt(src_lines: list[str], class_node: ast.ClassDef) -> bool:
    """Return True when the class carries # scope: process-internal exemption.

    Looks at: (a) the class declaration line itself, (b) the line immediately
    above the class (or above its decorators), and (c) the first line of the
    class docstring/body up to a few lines.
    """
    # Determine the topmost line owned by this class definition (decorator line).
    if class_node.decorator_list:
        top_lineno = min(
            (d.lineno for d in class_node.decorator_list), default=class_node.lineno
        )
    else:
        top_lineno = class_node.lineno
    # Inspect a small window of lines around the class definition.
    candidates: list[int] = [
        top_lineno - 1,  # line above decorator/class
        class_node.lineno,  # class def line
    ]
    candidates.extend(range(class_node.lineno + 1, min(class_node.lineno + 4, len(src_lines) + 1)))
    for ln in candidates:
        if 1 <= ln <= len(src_lines) and EXEMPT_MARKER in src_lines[ln - 1]:
            return True
    return False


def _class_has_field(class_node: ast.ClassDef, field_name: str) -> bool:
    """Return True when the dataclass body declares ``field_name`` as an annotated attribute."""
    for item in class_node.body:
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and item.target.id == field_name
        ):
            return True
        # Also consider plain Assign (rare in dataclasses but keep defensive).
        if isinstance(item, ast.Assign):
            for t in item.targets:
                if isinstance(t, ast.Name) and t.id == field_name:
                    return True
    return False


def _class_inherits_from_spine_base(
    class_node: ast.ClassDef, classes_with_tenant: set[str]
) -> bool:
    """Return True when the class lists a base that has tenant_id.

    AST-only check: matches simple ``Name`` bases against the corpus-wide set
    of dataclasses that declare tenant_id directly.  Cross-file inheritance is
    supported as long as both classes appear in the scanned set.
    """
    for base in class_node.bases:
        if isinstance(base, ast.Name) and base.id in classes_with_tenant:
            return True
        if isinstance(base, ast.Attribute) and base.attr in classes_with_tenant:
            return True
    return False


def _scan_file(rel_path: str, classes_with_tenant: set[str]) -> list[dict]:
    """Scan one file; return list of violation dicts."""
    full = REPO_ROOT / rel_path
    if not full.exists():
        return []
    src = full.read_text(encoding="utf-8")
    src_lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=str(full))
    except SyntaxError as exc:
        return [{
            "file": rel_path,
            "class": "<parse-error>",
            "lineno": 0,
            "reason": f"SyntaxError: {exc}",
        }]
    violations: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_is_dataclass_decorator(d) for d in node.decorator_list):
            continue
        if _class_is_exempt(src_lines, node):
            continue
        if _class_has_field(node, REQUIRED_FIELD):
            continue
        if _class_inherits_from_spine_base(node, classes_with_tenant):
            continue
        violations.append({
            "file": rel_path,
            "class": node.name,
            "lineno": node.lineno,
            "reason": (
                f"@dataclass {node.name} missing required '{REQUIRED_FIELD}' field "
                f"(add it or annotate the class with '{EXEMPT_MARKER}')"
            ),
        })
    return violations


def _collect_classes_with_tenant(files: list[str]) -> set[str]:
    """First pass: find every dataclass that has a tenant_id field declared.

    Used to recognise inheritance chains where a subclass omits tenant_id but
    extends a base that already declares it.
    """
    classes: set[str] = set()
    for rel in files:
        full = REPO_ROOT / rel
        if not full.exists():
            continue
        try:
            tree = ast.parse(full.read_text(encoding="utf-8"), filename=str(full))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_is_dataclass_decorator(d) for d in node.decorator_list):
                continue
            if _class_has_field(node, REQUIRED_FIELD):
                classes.add(node.name)
    return classes


def _gather_files() -> list[str]:
    files: list[str] = []
    for directory in SCAN_DIRS:
        d = REPO_ROOT / directory
        if not d.exists():
            continue
        for path in sorted(d.rglob("*.py")):
            if path.name.startswith("_") and path.name != "__init__.py":
                # Skip private helper modules like _spine_validation.py
                continue
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            files.append(rel)
    for f in SCAN_FILES:
        if (REPO_ROOT / f).exists():
            files.append(f)
    return files


def _emit_json(status: str, missing: list[dict], scanned: int) -> None:
    """Emit a multistatus JSON payload (or plain JSON when helper missing)."""
    payload = {
        "status": status,
        "check": "contract_spine_completeness",
        "scanned_files": scanned,
        "missing": missing,
    }
    try:
        from scripts._governance.multistatus import emit_and_exit  # type: ignore
    except Exception:
        print(json.dumps(payload, indent=2))
        sys.exit(0 if status == "pass" else 1)
    emit_and_exit(
        status=status,
        check="contract_spine_completeness",
        json_output=True,
        scanned_files=scanned,
        missing=missing,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contract spine completeness gate (Rule 12).")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args(argv)

    files = _gather_files()
    classes_with_tenant = _collect_classes_with_tenant(files)
    violations: list[dict] = []
    for rel in files:
        violations.extend(_scan_file(rel, classes_with_tenant))

    if args.json:
        _emit_json("fail" if violations else "pass", violations, len(files))
        return 1 if violations else 0  # pragma: no cover (emit_and_exit calls sys.exit)

    if violations:
        print(
            f"FAIL: {len(violations)} dataclass(es) missing required '{REQUIRED_FIELD}':",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  {v['file']}:{v['lineno']}: {v['class']} — {v['reason']}", file=sys.stderr)
        return 1
    print(f"PASS: contract spine completeness ({len(files)} files scanned, 0 missing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CI gate: restrict imports of ``_admin_session_store`` to admin/test allowlist.

W32 Track B Gap 4: the unscoped admin accessor for SessionStore lives in
``hi_agent/server/_admin_session_store.py``. Tenant-facing route handlers
and middleware MUST NOT import it; the only legitimate importers are admin
tooling and tests.

This gate walks every .py file under ``hi_agent/`` and ``agent_server/``
and rejects any import of ``hi_agent.server._admin_session_store`` or
``hi_agent.server._admin_session_store.<name>`` from a non-allowlisted
file. Tests are exempt (the test directory is intentionally NOT scanned;
test fixtures legitimately need cross-tenant assertions).

Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Modules whose imports MUST be allowlisted.
TARGET_MODULE = "hi_agent.server._admin_session_store"

# Repo-relative POSIX paths permitted to import the target.
# Tenant-facing route handlers and middleware are deliberately NOT listed.
ALLOWED_IMPORTERS: frozenset[str] = frozenset({
    # The module itself (self-import is a no-op but tolerated for re-exports).
    "hi_agent/server/_admin_session_store.py",
    # No production importer at this time. Admin tooling (operator drills,
    # restart-survival harnesses) SHOULD live under tests/ or scripts/ — both
    # are exempt by directory exclusion.
})

# Directories to scan.  Tests are intentionally NOT scanned: test fixtures
# legitimately need cross-tenant assertions and live outside the public path.
SCAN_DIRS = ("hi_agent", "agent_server")

SKIP_DIRS = frozenset({"venv", ".venv", "node_modules", ".git", "dist", "build", "__pycache__"})


def _walk(root: Path):
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def _file_imports_target(py_file: Path) -> list[int]:
    """Return list of line numbers where the file imports the target module."""
    try:
        src = py_file.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(src, filename=str(py_file))
    except SyntaxError:
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == TARGET_MODULE or alias.name.startswith(
                    TARGET_MODULE + "."
                ):
                    hits.append(node.lineno)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                node.module == TARGET_MODULE
                or node.module.startswith(TARGET_MODULE + ".")
            )
        ):
            hits.append(node.lineno)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON status")
    args = parser.parse_args()

    violations: list[dict[str, object]] = []
    scanned = 0
    for scan_dir in SCAN_DIRS:
        root = REPO_ROOT / scan_dir
        if not root.exists():
            continue
        for py in _walk(root):
            scanned += 1
            rel = py.relative_to(REPO_ROOT).as_posix()
            if rel in ALLOWED_IMPORTERS:
                continue
            hits = _file_imports_target(py)
            for line in hits:
                violations.append(
                    {"file": rel, "line": line, "module": TARGET_MODULE}
                )

    status = "pass" if not violations else "fail"

    if args.json:
        print(json.dumps({
            "status": status,
            "scanned_files": scanned,
            "violations": violations,
            "allowed_importers": sorted(ALLOWED_IMPORTERS),
            "target_module": TARGET_MODULE,
        }, indent=2))
    else:
        if violations:
            print(
                f"FAIL: {len(violations)} non-allowlisted import(s) of "
                f"{TARGET_MODULE!r}:"
            )
            for v in violations:
                print(f"  {v['file']}:{v['line']} imports {v['module']}")
            print(
                "Tenant-facing code MUST NOT import the admin shim. Use "
                "SessionStore.get_for_tenant() instead."
            )
        else:
            print(
                f"PASS: admin session store imports ({scanned} files scanned, "
                f"target={TARGET_MODULE})"
            )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

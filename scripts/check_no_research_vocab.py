#!/usr/bin/env python3
"""CI gate: hi_agent/ source must not contain research-domain vocabulary in identifiers.

Checks identifier names (not string values) that embed research-domain terms.
Allowlist entries carry # legacy: annotations in source.
Shim files are allowlisted by path.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
HI_AGENT = ROOT / "hi_agent"

# Files that are the shim/compat layer — allowed to reference old names
_PATH_ALLOWLIST = {
    "hi_agent/contracts/team_runtime.py",
    "hi_agent/server/team_run_registry.py",
    "hi_agent/evolve/contracts.py",
    "hi_agent/evolve/postmortem.py",
    "hi_agent/artifacts/contracts.py",
}

# Identifier names forbidden in new production code
_FORBIDDEN_IDENTIFIERS = {
    "pi_run_id",
    "apply_research_defaults",
}

# Class names forbidden as construction targets
_FORBIDDEN_CONSTRUCTIONS = {
    "RunPostmortem",
    "ProjectPostmortem",
    "EvolutionExperiment",
}

_LEGACY_ANNOTATION = "# legacy:"


def _rel(path: Path) -> str:
    """Return a repo-relative string, or the absolute path for out-of-tree files."""
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _is_allowlisted(path: Path) -> bool:
    return _rel(path) in _PATH_ALLOWLIST


def check_file(path: Path) -> list[str]:
    if _is_allowlisted(path):
        return []
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    lines = src.splitlines()
    issues = []
    label = _rel(path)

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", 0)
        line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if _LEGACY_ANNOTATION in line_text:
            continue

        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_IDENTIFIERS:
            issues.append(
                f"  {label}:{lineno}: .{node.attr} — research vocab"
            )
        if isinstance(node, ast.keyword) and node.arg in _FORBIDDEN_IDENTIFIERS:
            issues.append(
                f"  {label}:{lineno}: {node.arg}= kwarg — research vocab"
            )

        if isinstance(node, ast.Call):
            func = node.func
            cls_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if cls_name in _FORBIDDEN_CONSTRUCTIONS:
                issues.append(
                    f"  {label}:{lineno}: {cls_name}() — use renamed class"
                )

    return issues


def main() -> int:
    errors = []
    for py_file in HI_AGENT.rglob("*.py"):
        errors.extend(check_file(py_file))
    if errors:
        print("FAIL check_no_research_vocab:")
        for e in errors:
            print(e)
        return 1
    print("OK check_no_research_vocab")
    return 0


if __name__ == "__main__":
    sys.exit(main())

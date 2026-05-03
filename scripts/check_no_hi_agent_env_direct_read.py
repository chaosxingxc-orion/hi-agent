#!/usr/bin/env python3
"""W33 Track E.1: CI gate — no production module reads HI_AGENT_ENV directly.

Per Rule 11, the canonical runtime mode lives behind
``hi_agent.config.posture.resolve_runtime_mode`` which honors
HI_AGENT_POSTURE first and falls back to HI_AGENT_ENV. Direct reads of
HI_AGENT_ENV split the truth across multiple sites with conflicting
defaults — same process can be both "dev" and "prod" simultaneously
depending on which builder is consulted.

This gate scans ``hi_agent/`` for ``os.environ.get("HI_AGENT_ENV", ...)``
or equivalent direct reads. Tests and the canonical helper module are
allowlisted. The diagnostic dump in ``hi_agent/server/ops_routes.py``
that surfaces the raw env var value to operators is also allowlisted.

Exit codes:
    0 — pass (no violations)
    1 — fail (one or more violations)

Flags:
    --json  Emit structured JSON report instead of human-readable output.
"""

# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
HI_AGENT = ROOT / "hi_agent"

# Files allowed to read HI_AGENT_ENV directly. Each entry must justify its
# presence:
#
#   - hi_agent/config/posture.py — canonical resolver (the single sanctioned
#     reader). All other modules call ``resolve_runtime_mode()``.
#
#   - hi_agent/server/ops_routes.py — operator diagnostic dump (/ops/runtime)
#     that surfaces the raw HI_AGENT_ENV value as data, not as logic input.
#     The runtime_mode used for actual decisions on this route already flows
#     through resolve_runtime_mode().
_PATH_ALLOWLIST: frozenset[str] = frozenset({
    "hi_agent/config/posture.py",
    "hi_agent/server/ops_routes.py",
})


def _rel(path: Path) -> str:
    """Return a repo-relative POSIX-style string."""
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _is_allowlisted(path: Path) -> bool:
    return _rel(path) in _PATH_ALLOWLIST


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _is_environ_get_for_hi_agent_env(node: ast.Call) -> bool:
    """Return True for ``os.environ.get("HI_AGENT_ENV", ...)`` calls."""
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "get":
        return False
    # node.func.value should be Attribute(value=Name(os|os_alias), attr=environ)
    value = node.func.value
    if not isinstance(value, ast.Attribute):
        return False
    if value.attr != "environ":
        return False
    if not node.args:
        return False
    first = node.args[0]
    if not isinstance(first, ast.Constant):
        return False
    return first.value == "HI_AGENT_ENV"


def _is_environ_subscript_for_hi_agent_env(node: ast.Subscript) -> bool:
    """Return True for ``os.environ["HI_AGENT_ENV"]`` subscript reads."""
    if not isinstance(node.value, ast.Attribute):
        return False
    if node.value.attr != "environ":
        return False
    slc = node.slice
    if not isinstance(slc, ast.Constant):
        return False
    return slc.value == "HI_AGENT_ENV"


def check_file(path: Path) -> list[dict]:
    """Return list of violation dicts for a single Python file."""
    if _is_allowlisted(path):
        return []
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []
    violations: list[dict] = []
    label = _rel(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_environ_get_for_hi_agent_env(node):
            violations.append({
                "file": label,
                "line": getattr(node, "lineno", 0),
                "kind": "environ.get",
                "advice": (
                    "Replace with "
                    "`from hi_agent.config.posture import resolve_runtime_mode; "
                    "resolve_runtime_mode()` (W33 Track E.1)."
                ),
            })
        elif isinstance(node, ast.Subscript) and _is_environ_subscript_for_hi_agent_env(node):
            violations.append({
                "file": label,
                "line": getattr(node, "lineno", 0),
                "kind": "environ[]",
                "advice": (
                    "Replace with "
                    "`from hi_agent.config.posture import resolve_runtime_mode; "
                    "resolve_runtime_mode()` (W33 Track E.1)."
                ),
            })
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check hi_agent/ for direct HI_AGENT_ENV reads (W33 Track E.1)."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit structured JSON report.",
    )
    args = parser.parse_args(argv)

    all_violations: list[dict] = []
    for py_file in HI_AGENT.rglob("*.py"):
        all_violations.extend(check_file(py_file))

    if args.json_output:
        report = {
            "check": "no_hi_agent_env_direct_read",
            "status": "fail" if all_violations else "pass",
            "violations": all_violations,
            "violation_count": len(all_violations),
            "allowlist": sorted(_PATH_ALLOWLIST),
            "head": _git_head(),
        }
        print(json.dumps(report, indent=2))
        return 1 if all_violations else 0

    if all_violations:
        print(f"FAIL check_no_hi_agent_env_direct_read ({len(all_violations)} violations):")
        for v in all_violations:
            print(f"  {v['file']}:{v['line']}: {v['kind']} — {v['advice']}")
        return 1

    print("OK check_no_hi_agent_env_direct_read")
    return 0


if __name__ == "__main__":
    sys.exit(main())

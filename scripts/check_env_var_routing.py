#!/usr/bin/env python3
"""W34-CONFIG-ENV-AUDIT gate.

Extends ``scripts/check_no_hi_agent_env_direct_read.py`` (W33-E.1) to cover
the four most policy-sensitive environment variables:

    - HI_AGENT_POSTURE
    - HI_AGENT_LLM_MODE
    - HI_AGENT_JWT_SECRET
    - AGENT_SERVER_BACKEND

For each, only the per-variable canonical reader site (and any
explicitly-allowlisted diagnostic / test-only consumer) may read the value
from ``os.environ``. Every other production module must reach the value
through the typed accessor.

The gate intentionally does NOT enforce single-site routing for long-tail
variables (data dirs, fault-injection toggles, etc.); those reads are
documented in ``docs/governance/env-var-audit-2026-05-04.md`` and live in
descriptively-named module entry points already.

Exit codes:
    0 — pass
    1 — fail (one or more unsanctioned direct reads)

Flags:
    --json  Emit structured JSON report instead of human-readable output.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCAN_ROOTS = (ROOT / "hi_agent", ROOT / "agent_server")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=ROOT, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# Per-variable allowlist. Values are sets of repo-relative POSIX paths.
# Each path documents *why* it is on the allowlist in
# docs/governance/env-var-audit-2026-05-04.md.
ALLOWLIST: dict[str, frozenset[str]] = {
    "HI_AGENT_POSTURE": frozenset({
        "hi_agent/config/posture.py",                    # canonical anchor
        "agent_server/api/routes_skills_memory.py",      # posture-aware route gate
        "agent_server/contracts/gate.py",                # __post_init__ posture-strict
        "hi_agent/operator_tools/diagnostics.py",        # diagnostic dump
    }),
    "HI_AGENT_LLM_MODE": frozenset({
        "hi_agent/config/json_config_loader.py",         # canonical settings-loader
        "hi_agent/server/ops_routes.py",                 # diagnostic dump
    }),
    "HI_AGENT_JWT_SECRET": frozenset({
        "agent_server/runtime/auth_seam.py",             # canonical auth seam
        "hi_agent/server/auth_middleware.py",            # legacy auth middleware
    }),
    "AGENT_SERVER_BACKEND": frozenset({
        "agent_server/bootstrap.py",                     # canonical bootstrap reader
    }),
}


def _is_environ_get_for(node: ast.Call, var_name: str) -> bool:
    """Return True for ``os.environ.get("<VAR>", ...)`` and friends."""
    func = node.func
    # os.environ.get("VAR", ...)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
    ):
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == var_name:
            return True
    # os.getenv("VAR", ...)
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == var_name:
            return True
    return False


def _is_environ_index_for(node: ast.Subscript, var_name: str) -> bool:
    """Return True for ``os.environ["<VAR>"]``."""
    if not (
        isinstance(node.value, ast.Attribute)
        and node.value.attr == "environ"
    ):
        return False
    sl = node.slice
    if isinstance(sl, ast.Constant) and sl.value == var_name:
        return True
    return False


def _scan_file(path: Path, var_name: str) -> list[int]:
    """Return line numbers in *path* where *var_name* is read directly."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_environ_get_for(node, var_name):
            hits.append(node.lineno)
        elif isinstance(node, ast.Subscript) and _is_environ_index_for(node, var_name):
            hits.append(node.lineno)
    return hits


def _scan_var(var_name: str, allowlist: frozenset[str]) -> list[tuple[str, int, str]]:
    """Return [(rel_path, lineno, var_name), ...] of unsanctioned reads."""
    violations: list[tuple[str, int, str]] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            rel = _rel(py)
            if rel in allowlist:
                continue
            for line in _scan_file(py, var_name):
                violations.append((rel, line, var_name))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    all_violations: list[tuple[str, int, str]] = []
    for var, allow in ALLOWLIST.items():
        all_violations.extend(_scan_var(var, allow))

    if args.json_output:
        print(json.dumps({
            "check": "env_var_routing",
            "status": "pass" if not all_violations else "fail",
            "violations": [
                {"file": v[0], "line": v[1], "var": v[2]}
                for v in all_violations
            ],
            "head": _git_head(),
            "vars_enforced": sorted(ALLOWLIST.keys()),
        }))
    else:
        if not all_violations:
            print(
                f"OK env_var_routing ({len(ALLOWLIST)} sensitive vars enforced; "
                "see docs/governance/env-var-audit-2026-05-04.md for the full inventory)"
            )
        else:
            print("FAIL env_var_routing:")
            for rel, line, var in all_violations:
                print(f"  {rel}:{line}  reads {var} directly (not on per-var allowlist)")
            print(
                "\n  Each policy-sensitive env var has a documented canonical reader. "
                "Route the read through the typed accessor or extend ALLOWLIST in this "
                "script with a rationale row in docs/governance/env-var-audit-2026-05-04.md."
            )
    return 0 if not all_violations else 1


if __name__ == "__main__":
    sys.exit(main())

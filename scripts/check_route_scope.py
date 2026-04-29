#!/usr/bin/env python3
"""CI gate: every authenticated route handler must enforce tenant scope.

Scans routes_*.py for async handle_* functions. Each function that calls
require_tenant_context() must also call one of the scoping primitives:
- validate_resource_ownership / get_or_404_owned
- manager.get_run(workspace=ctx)
- registry.get(..., tenant_id=ctx.tenant_id)
- registry.query(..., tenant_id=ctx.tenant_id)
- _belongs_to_tenant
- tenant_id=ctx.tenant_id  (direct kwarg assignment)
- ctx.tenant_id != / == / in  (inline comparison)
- _resolve_profile_id(ctx  (memory route tenant derivation)
- admin_required  (admin-scope gate)

Exceptions (decorated with noqa-no-tenant-scope marker or in NO_SCOPE_ALLOWLIST):
- /health, /ready, /metrics, /manifest, /cost endpoints
- handlers that list runs scoped by workspace (manager.list_runs)

Allowlist source: docs/governance/allowlists.yaml :: route_scope_allowlist
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _current_wave import is_expired

ROOT = Path(__file__).parent.parent
_ALLOWLISTS_FILE = ROOT / "docs" / "governance" / "allowlists.yaml"

SCOPE_INDICATORS = frozenset({
    "validate_resource_ownership",
    "get_or_404_owned",
    "get_run",
    "_belongs_to_tenant",
    "_resolve_profile_id",
    "admin_required",
    "get_for_tenant",
})


@dataclass(frozen=True)
class AllowlistEntry:
    reason: str        # why this handler doesn't need per-resource tenant scoping
    risk: str          # what could go wrong if abused
    owner: str         # who's accountable (CO|RO|DX|TE|GOV)
    expiry_wave: str   # "permanent" or "Wave NN" when this entry must be removed
    replacement_test: str  # test file that will cover this when entry is removed
    contract: str = ""     # "global-readonly" | "admin-only" | "system-info" | ""


def _load_route_scope_allowlist() -> dict[str, AllowlistEntry]:
    """Load route scope allowlist from docs/governance/allowlists.yaml.

    Falls back to empty dict (gates fail-closed) if the file cannot be read.
    """
    try:
        import yaml
        with open(_ALLOWLISTS_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        entries = data.get("route_scope_allowlist", [])
        result: dict[str, AllowlistEntry] = {}
        for e in entries:
            name = e.get("name", "")
            if not name:
                continue
            result[name] = AllowlistEntry(
                reason=e.get("reason", ""),
                risk=e.get("risk", ""),
                owner=e.get("owner", ""),
                expiry_wave=str(e.get("expiry_wave", "")),
                replacement_test=e.get("replacement_test", ""),
                contract=e.get("contract", ""),
            )
        return result
    except Exception as exc:
        print(
            f"WARNING: failed to load route_scope_allowlist from {_ALLOWLISTS_FILE}: {exc}",
            file=sys.stderr,
        )
        return {}


NO_SCOPE_ALLOWLIST: dict[str, AllowlistEntry] = _load_route_scope_allowlist()


def _validate_allowlist() -> list[str]:
    """Validate that all allowlist entries have required fields."""
    issues = []
    for handler_name, entry in NO_SCOPE_ALLOWLIST.items():
        if not entry.reason:
            issues.append(f"Allowlist entry '{handler_name}' has empty reason")
        if not entry.owner:
            issues.append(f"Allowlist entry '{handler_name}' has empty owner")
        if not entry.expiry_wave:
            issues.append(f"Allowlist entry '{handler_name}' has empty expiry_wave")
        if not entry.replacement_test:
            issues.append(f"Allowlist entry '{handler_name}' has empty replacement_test")
    return issues


def _check_expiry(entries: dict) -> list[str]:
    """Return list of error strings for entries whose expiry_wave has passed."""
    errors = []
    for route_name, entry in entries.items():
        expiry = entry.expiry_wave if entry.expiry_wave else None
        if expiry and expiry != "permanent" and is_expired(expiry):
            errors.append(
                f"Allowlist entry {route_name!r} expired (expiry_wave={expiry!r}). "
                f"Replace with real per-tenant filter or bump expiry_wave with documented reason."
            )
    return errors


def check_file(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"  {path.relative_to(ROOT)}: SyntaxError: {exc}"]
    errors = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not node.name.startswith("handle_"):
            continue
        if node.name in NO_SCOPE_ALLOWLIST:
            continue
        func_src = ast.get_source_segment(src, node) or ""
        if "noqa: no-tenant-scope" in func_src:
            continue
        if "require_tenant_context" not in func_src:
            continue  # not authenticated -- skip
        # Check for scope indicators
        has_scope = any(indicator in func_src for indicator in SCOPE_INDICATORS)
        has_tenant_id_usage = (
            "tenant_id=ctx.tenant_id" in func_src
            or "ctx.tenant_id !=" in func_src
            or "ctx.tenant_id ==" in func_src
            or "ctx.tenant_id in " in func_src
            or "!= ctx.tenant_id" in func_src
        )
        if not (has_scope or has_tenant_id_usage):
            errors.append(
                f"  {path.relative_to(ROOT)}::{node.name}: "
                f"authenticated but no tenant scope filter found"
            )
    return errors


def _get_head_sha() -> str:
    """Return short git HEAD SHA, or empty string on failure."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Validate allowlist entries first
    allowlist_issues = _validate_allowlist()
    if allowlist_issues:
        if args.json:
            print(json.dumps({
                "check": "route_scope",
                "status": "fail",
                "allowlist_total": len(NO_SCOPE_ALLOWLIST),
                "allowlist_expired": 0,
                "expiring_this_wave": 0,
                "violations": allowlist_issues,
                "head": _get_head_sha(),
            }))
        else:
            print("FAIL check_route_scope (allowlist validation):")
            for issue in allowlist_issues:
                print(f"  {issue}")
        return 1

    # Check for expired allowlist entries
    expiry_errors = _check_expiry(NO_SCOPE_ALLOWLIST)

    # Scan route handlers for missing tenant scope
    scope_errors = []
    for path in ROOT.glob("hi_agent/server/routes_*.py"):
        scope_errors.extend(check_file(path))
    app_path = ROOT / "hi_agent" / "server" / "app.py"
    if app_path.exists():
        scope_errors.extend(check_file(app_path))

    all_violations = expiry_errors + scope_errors

    # Count expired and expiring entries
    allowlist_total = len(NO_SCOPE_ALLOWLIST)
    allowlist_expired = len(expiry_errors)

    if args.json:
        sha = _get_head_sha()
        status = "fail" if all_violations else "pass"
        print(json.dumps({
            "check": "route_scope",
            "status": status,
            "allowlist_total": allowlist_total,
            "allowlist_expired": allowlist_expired,
            "expiring_this_wave": allowlist_expired,
            "violations": all_violations,
            "head": sha,
        }))
        return 1 if all_violations else 0

    if expiry_errors:
        print("FAIL check_route_scope (expired allowlist entries):")
        for e in expiry_errors:
            print(f"  {e}")
        return 1

    if scope_errors:
        print("FAIL check_route_scope:")
        for e in scope_errors:
            print(e)
        return 1

    print("OK check_route_scope")

    # Allowlist count tracking
    print(f"ALLOWLIST: {allowlist_total} entries")

    baseline_file = ROOT / "docs" / "allowlist-baseline.txt"
    if baseline_file.exists():
        try:
            baseline = int(baseline_file.read_text().strip())
            if allowlist_total > baseline:
                print(f"FAIL: Allowlist grew from {baseline} to {allowlist_total} entries")
                print(
                    "Remove stale allowlist entries or update docs/allowlist-baseline.txt"
                    " if growth is justified"
                )
                return 1
            elif allowlist_total < baseline:
                print(f"NOTE: Allowlist reduced from {baseline} to {allowlist_total} (good)")
        except ValueError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

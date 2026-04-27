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

Exceptions (decorated with # noqa: no-tenant-scope or in NO_SCOPE_ALLOWLIST):
- /health, /ready, /metrics, /manifest, /cost endpoints
- handlers that list runs scoped by workspace (manager.list_runs)
"""
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

SCOPE_INDICATORS = frozenset({
    "validate_resource_ownership",
    "get_or_404_owned",
    "get_run",
    "_belongs_to_tenant",
    "_resolve_profile_id",
    "admin_required",
})


@dataclass(frozen=True)
class AllowlistEntry:
    reason: str        # why this handler doesn't need per-resource tenant scoping
    risk: str          # what could go wrong if abused
    owner: str         # who's accountable (CO|RO|DX|TE|GOV)
    expiry_wave: str   # "permanent" or "Wave NN" when this entry must be removed
    replacement_test: str  # test file that will cover this when entry is removed
    contract: str = ""     # "global-readonly" | "admin-only" | "system-info" | ""


NO_SCOPE_ALLOWLIST: dict[str, AllowlistEntry] = {
    # System/health endpoints — no per-resource data
    "handle_health": AllowlistEntry(
        reason="Health check endpoint — process-level status, no tenant data",
        risk="None — no per-tenant data",
        owner="DX",
        expiry_wave="permanent",
        replacement_test="test_routes_health.py",
        contract="system-info",
    ),
    "handle_ready": AllowlistEntry(
        reason="Readiness probe — process-level startup check, no tenant data",
        risk="None — no per-tenant data",
        owner="DX",
        expiry_wave="permanent",
        replacement_test="test_routes_health.py",
        contract="system-info",
    ),
    "handle_metrics": AllowlistEntry(
        reason="Prometheus metrics — aggregate counters, no per-tenant data in labels",
        risk="Low — counter names could reveal capability usage patterns",
        owner="DX",
        expiry_wave="permanent",
        replacement_test="test_routes_metrics_no_tenant_leak.py",
        contract="system-info",
    ),
    "handle_manifest": AllowlistEntry(
        reason="System capabilities manifest — identical payload for all tenants",
        risk="None — no per-tenant data exposed; global read-only",
        owner="DX",
        expiry_wave="permanent",
        replacement_test="test_routes_manifest_global_contract.py",
        contract="global-readonly",
    ),
    "handle_cost": AllowlistEntry(
        reason="Cost estimation endpoint — returns model pricing, not tenant-specific spend",
        risk="Low — could reveal model pricing structure; no per-tenant cost data",
        owner="DX",
        expiry_wave="permanent",
        replacement_test="test_routes_cost_no_tenant_leak.py",
        contract="global-readonly",
    ),
    "handle_capacity_advice": AllowlistEntry(
        reason="Capacity advice — system-wide capacity signals, not per-tenant quota",
        risk="Low — reveals system load; no per-tenant data",
        owner="DX",
        expiry_wave="permanent",
        replacement_test="test_routes_capacity_no_tenant_leak.py",
        contract="system-info",
    ),
    # Run list/lifecycle — workspace scoping is done inside run_manager
    "handle_list_runs": AllowlistEntry(
        reason="Run listing — workspace-scoped inside run_manager.list_runs(workspace=ctx)",
        risk="Medium — if run_manager scoping is bypassed, cross-tenant leak possible",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_runs_tenant_isolation.py",
        contract="",
    ),
    "handle_runs_active": AllowlistEntry(
        reason="Active run listing — workspace-scoped inside run_manager",
        risk="Medium — same risk as handle_list_runs",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_runs_tenant_isolation.py",
        contract="",
    ),
    "handle_get_run": AllowlistEntry(
        reason="Single run fetch — workspace-scoped via run_manager.get_run(workspace=ctx)",
        risk="Medium — if workspace check is bypassed, cross-tenant run read possible",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_runs_tenant_isolation.py",
        contract="",
    ),
    "handle_signal_run": AllowlistEntry(
        reason="Run signal — workspace-scoped ownership verified inside run_manager",
        risk="Medium — unauthorized signal could abort another tenant's run",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_runs_tenant_isolation.py",
        contract="",
    ),
    "handle_cancel_run": AllowlistEntry(
        reason="Run cancellation — workspace-scoped ownership verified inside run_manager",
        risk="Medium — unauthorized cancel could abort another tenant's run",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_runs_tenant_isolation.py",
        contract="",
    ),
    "handle_submit_feedback": AllowlistEntry(
        reason="Feedback submission — run_id scoped; feedback tied to run (workspace-scoped)",
        risk="Medium — must verify run ownership before accepting feedback",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_feedback_tenant_isolation.py",
        contract="",
    ),
    "handle_get_feedback": AllowlistEntry(
        reason="Feedback retrieval — run_id scoped; run ownership enforced inside run_manager",
        risk="Medium — must verify run ownership before returning feedback",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_feedback_tenant_isolation.py",
        contract="",
    ),
    "handle_resume_run": AllowlistEntry(
        reason="Run resume — workspace-scoped ownership verified inside run_manager",
        risk="Medium — unauthorized resume could hijack another tenant's run",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_runs_tenant_isolation.py",
        contract="",
    ),
    "handle_run_artifacts": AllowlistEntry(
        reason="Run artifact listing — run_id scoped; run ownership enforced inside run_manager",
        risk="Medium — must verify run ownership before returning artifact list",
        owner="TE",
        expiry_wave="permanent",
        replacement_test="test_routes_artifacts_tenant_isolation.py",
        contract="",
    ),
    # Memory status — profile derived from ctx (handled by _resolve_profile_id)
    "handle_memory_status": AllowlistEntry(
        reason="Memory status — profile_id from ctx via _resolve_profile_id; tenant implicit",
        risk="Low — _resolve_profile_id enforces ctx-to-profile binding; no cross-tenant access",
        owner="RO",
        expiry_wave="permanent",
        replacement_test="test_routes_memory_tenant_isolation.py",
        contract="",
    ),
    # Knowledge routes — system-wide knowledge, no per-tenant resource isolation
    "handle_knowledge_ingest": AllowlistEntry(
        reason="Knowledge ingest — global KG, per-tenant isolation not yet implemented; Wave 14",
        risk="High — ingest without tenant scope could pollute shared graph across tenants",
        owner="RO",
        expiry_wave="Wave 15",
        replacement_test="test_routes_knowledge_tenant_isolation.py",
        contract="",
    ),
    "handle_knowledge_ingest_structured": AllowlistEntry(
        reason="Structured knowledge ingest — same scope gap as handle_knowledge_ingest; Wave 14",
        risk="High — same risk as handle_knowledge_ingest",
        owner="RO",
        expiry_wave="Wave 15",
        replacement_test="test_routes_knowledge_tenant_isolation.py",
        contract="",
    ),
    "handle_knowledge_query": AllowlistEntry(
        reason="Knowledge query — global graph, per-tenant filtering not yet implemented; Wave 14",
        risk="High — query without tenant scope returns cross-tenant knowledge nodes",
        owner="RO",
        expiry_wave="Wave 15",
        replacement_test="test_routes_knowledge_tenant_isolation.py",
        contract="",
    ),
    "handle_knowledge_status": AllowlistEntry(
        reason="Knowledge status — system-wide KG stats; tenant-isolation not yet impl; Wave 14",
        risk="Low — reveals aggregate KG size; no per-tenant node data",
        owner="RO",
        expiry_wave="Wave 15",
        replacement_test="test_routes_knowledge_tenant_isolation.py",
        contract="system-info",
    ),
    "handle_knowledge_lint": AllowlistEntry(
        reason="Knowledge lint — stateless validation; tenant-isolation not yet impl; Wave 14",
        risk="Low — lint result is stateless; no stored per-tenant data access",
        owner="RO",
        expiry_wave="Wave 15",
        replacement_test="test_routes_knowledge_tenant_isolation.py",
        contract="",
    ),
    "handle_knowledge_sync": AllowlistEntry(
        reason="Knowledge sync — system-wide sync, per-tenant scope not yet implemented; Wave 14",
        risk="High — sync without tenant scope could overwrite cross-tenant knowledge",
        owner="RO",
        expiry_wave="Wave 15",
        replacement_test="test_routes_knowledge_tenant_isolation.py",
        contract="",
    ),
    # Skills routes — global skill registry, no per-tenant resource isolation
    "handle_skills_list": AllowlistEntry(
        reason="Skills listing — global registry, per-tenant overlay not yet implemented; Wave 14",
        risk="Low — all tenants see all skills; no secret per-tenant skills exposed",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="global-readonly",
    ),
    "handle_skills_status": AllowlistEntry(
        reason="Skills status — system-wide skill health; tenant-isolation not yet impl; Wave 14",
        risk="Low — reveals aggregate skill availability; no per-tenant data",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="system-info",
    ),
    "handle_skills_evolve": AllowlistEntry(
        reason="Skill evolution — global trigger, per-tenant scope not yet implemented; Wave 14",
        risk="High — evolution without tenant scope could modify skills used by other tenants",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="",
    ),
    "handle_skill_metrics": AllowlistEntry(
        reason="Skill metrics — aggregate counters; tenant-isolation not yet implemented; Wave 14",
        risk="Low — reveals skill usage patterns; no per-tenant data in current implementation",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="system-info",
    ),
    "handle_skill_versions": AllowlistEntry(
        reason="Skill versions — global version history; tenant-isolation not yet impl; Wave 14",
        risk="Low — version list is global; no per-tenant version isolation",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="global-readonly",
    ),
    "handle_skill_optimize": AllowlistEntry(
        reason="Skill optimization — global trigger, per-tenant scope not yet implemented; Wave 14",
        risk="High — optimization without tenant scope could degrade shared skill quality",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="",
    ),
    "handle_skill_promote": AllowlistEntry(
        reason="Skill promotion — global promotion, per-tenant approval not yet impl; Wave 14",
        risk="High — promotion without tenant scope could affect all tenant skill availability",
        owner="TE",
        expiry_wave="Wave 15",
        replacement_test="test_routes_skills_tenant_overlay.py",
        contract="",
    ),
    # Tools/MCP — invocation routes, tenant injected via ctx downstream
    "handle_tools_call": AllowlistEntry(
        reason="Tool invocation — tenant_id injected downstream; per-tenant filter absent; Wave 14",
        risk="Medium — must verify tool call context carries tenant_id before execution",
        owner="DX",
        expiry_wave="Wave 15",
        replacement_test="test_routes_tools_tenant_injection.py",
        contract="",
    ),
    "handle_tools_list": AllowlistEntry(
        reason="Tool listing — global registry, per-tenant filtering not yet implemented; Wave 14",
        risk="Low — all tenants see all tools; no secret per-tenant tools in current impl",
        owner="DX",
        expiry_wave="Wave 15",
        replacement_test="test_routes_tools_tenant_injection.py",
        contract="global-readonly",
    ),
    "handle_mcp_tools": AllowlistEntry(
        reason="MCP tools root handler — global registry, per-tenant overlay not yet impl; Wave 14",
        risk="Low — no per-tenant data exposed in tool server listing",
        owner="DX",
        expiry_wave="Wave 15",
        replacement_test="test_routes_tools_tenant_injection.py",
        contract="global-readonly",
    ),
    "handle_mcp_tools_list": AllowlistEntry(
        reason="MCP tool listing — global registry, per-tenant filtering not yet impl; Wave 14",
        risk="Low — same risk as handle_tools_list",
        owner="DX",
        expiry_wave="Wave 15",
        replacement_test="test_routes_tools_tenant_injection.py",
        contract="global-readonly",
    ),
    "handle_mcp_tools_call": AllowlistEntry(
        reason="MCP tool invocation — tenant_id injected downstream; per-tenant filter absent; W14",
        risk="Medium — same risk as handle_tools_call",
        owner="DX",
        expiry_wave="Wave 15",
        replacement_test="test_routes_tools_tenant_injection.py",
        contract="",
    ),
}


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
            continue  # not authenticated — skip
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

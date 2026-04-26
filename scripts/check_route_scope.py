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

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

SCOPE_INDICATORS = frozenset({
    "validate_resource_ownership",
    "get_or_404_owned",
    "get_run",
    "list_runs",
    "_belongs_to_tenant",
    "_resolve_profile_id",
    "admin_required",
    "require_tenant_owns",
})

NO_SCOPE_ALLOWLIST = frozenset({
    # System/info endpoints — authenticated but no per-resource data returned
    "handle_manifest",    # system capabilities manifest — same for all tenants
    "handle_cost",        # LLM cost summary — aggregate, not per-tenant resource
    "handle_capacity_advice",  # advisory capacity tuning — no per-tenant resource
    # Knowledge routes — system-wide knowledge, no per-tenant resource isolation (Wave 10.1)
    # W5-G: per-tenant knowledge scoping deferred; system-wide graph serves all tenants.
    "handle_knowledge_ingest",
    "handle_knowledge_ingest_structured",
    "handle_knowledge_query",
    "handle_knowledge_status",
    "handle_knowledge_lint",
    "handle_knowledge_sync",
    # Skills routes — global skill registry, no per-tenant resource isolation (Wave 10.1)
    # W5-G: TODO per-tenant skill overlay; global registry serves all tenants for now.
    "handle_skills_list",
    "handle_skills_status",
    "handle_skills_evolve",
    "handle_skill_metrics",
    "handle_skill_versions",
    "handle_skill_optimize",
    "handle_skill_promote",
    # Tools/MCP — invocation routes, tenant injected via ctx downstream (Wave 10.1)
    "handle_tools_call",
})


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


def main() -> int:
    errors = []
    for path in ROOT.glob("hi_agent/server/routes_*.py"):
        errors.extend(check_file(path))
    # Also check app.py for inline handlers
    app_path = ROOT / "hi_agent" / "server" / "app.py"
    if app_path.exists():
        errors.extend(check_file(app_path))
    if errors:
        print("FAIL check_route_scope:")
        for e in errors:
            print(e)
        return 1
    print("OK check_route_scope")
    return 0


if __name__ == "__main__":
    sys.exit(main())

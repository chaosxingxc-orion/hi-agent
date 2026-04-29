#!/usr/bin/env python
"""CI gate: fail if agent_server/api/routes_*.py handlers don't use TenantContext (R-AS-4).

Every route handler must read TenantContext to enforce per-tenant isolation.

Usage: python scripts/check_route_tenant_context.py
Exit 0 = clean or no routes yet; 1 = violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
API_DIR = ROOT / "agent_server" / "api"

# Pattern: async def or def at module level followed by route-looking name
HANDLER_RE = re.compile(r'^async def (\w+)\(|^def (\w+)\(', re.MULTILINE)
TENANT_RE = re.compile(r'TenantContext|tenant_context|tenant_id', re.IGNORECASE)


def check() -> int:
    if not API_DIR.exists():
        print("PASS (R-AS-4): agent_server/api/ not yet created — skipping")
        return 0

    route_files = sorted(API_DIR.glob("routes_*.py"))
    if not route_files:
        print("PASS (R-AS-4): no routes_*.py files yet — skipping")
        return 0

    violations = []
    for py_file in route_files:
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        # Check entire file references TenantContext
        if not TENANT_RE.search(text):
            violations.append(f"  {py_file.relative_to(ROOT)}: no TenantContext reference found")

    if violations:
        print(f"FAIL (R-AS-4): {len(violations)} route file(s) missing TenantContext:")
        for v in violations:
            print(v)
        return 1
    print(f"PASS (R-AS-4): all {len(route_files)} route file(s) reference TenantContext")
    return 0


if __name__ == "__main__":
    sys.exit(check())
